"""Logical restore and cross-account import without replaying tool calls."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from uuid import uuid4

import ijson
from pydantic import BaseModel, ConfigDict, Field

from codex_session_manager.app_server import SubprocessAppServer
from codex_session_manager.audit import AuditStore
from codex_session_manager.config import AppPaths
from codex_session_manager.hashing import fingerprint, hash_file, utc_now
from codex_session_manager.inventory import model_visible_messages
from codex_session_manager.models import (
    CapabilityMatrix,
    ImportCandidate,
    ImportDisposition,
    ImportPlan,
    ThreadSnapshot,
)


class ImportError(RuntimeError):
    pass


MAX_CODEX_JSONL_LINE_BYTES = 64 * 1024 * 1024


class ImportMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: float | None = None


class InertSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    execute: Literal[False] = False


class ConversationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    source_type: str
    source_account: str | None = None
    source_thread_id: str | None = None
    branch_path: tuple[str, ...] = ()
    title: str = ""
    messages: tuple[ImportMessage, ...]
    sidecars: tuple[InertSidecar, ...] = ()
    suggested_cwd: str | None = None
    suggested_git_remote: str | None = None

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            tuple({"role": message.role, "text": message.text} for message in self.messages)
        )

    def is_prefix_of(self, other: Self) -> bool:
        if len(self.messages) > len(other.messages):
            return False
        return all(
            left.role == right.role and left.text == right.text
            for left, right in zip(self.messages, other.messages, strict=False)
        )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        parts = content.get("parts")
        if isinstance(parts, list):
            return "\n".join(_content_text(part) for part in parts if _content_text(part))
        text = content.get("text")
        if isinstance(text, str):
            return text
        result = content.get("result")
        if isinstance(result, str):
            return result
    if isinstance(content, list):
        return "\n".join(_content_text(part) for part in content if _content_text(part))
    return ""


def _chatgpt_message(
    node_id: str, node: Mapping[str, Any]
) -> tuple[ImportMessage | None, InertSidecar | None]:
    message = node.get("message")
    if not isinstance(message, Mapping):
        return None, None
    author = message.get("author")
    role = author.get("role") if isinstance(author, Mapping) else None
    text = _content_text(message.get("content")).strip()
    message_id = message.get("id") if isinstance(message.get("id"), str) else node_id
    if role in {"user", "assistant"} and text:
        return (
            ImportMessage(
                source_id=message_id,
                role=role,
                text=text,
                created_at=(
                    float(message["create_time"])
                    if isinstance(message.get("create_time"), (int, float))
                    else None
                ),
            ),
            None,
        )
    if message:
        return None, InertSidecar(
            source_id=message_id,
            kind=f"chatgpt:{role or 'unknown'}",
            payload={"message": dict(message)},
        )
    return None, None


def _branch_paths(mapping: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    parents: dict[str, str | None] = {}
    children: dict[str, set[str]] = defaultdict(set)
    for node_id, raw_node in mapping.items():
        if not isinstance(raw_node, Mapping):
            continue
        parent_value = raw_node.get("parent")
        parent = parent_value if isinstance(parent_value, str) and parent_value in mapping else None
        parents[node_id] = parent
        if parent:
            children[parent].add(node_id)
        child_values = raw_node.get("children")
        if isinstance(child_values, list):
            for child in child_values:
                if isinstance(child, str) and child in mapping:
                    children[node_id].add(child)
                    parents.setdefault(child, node_id)
    leaves = sorted(node_id for node_id in parents if not children.get(node_id))
    paths: list[tuple[str, ...]] = []
    for leaf in leaves:
        reverse_path: list[str] = []
        current: str | None = leaf
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ImportError(f"cycle in ChatGPT conversation graph at {current}")
            seen.add(current)
            reverse_path.append(current)
            current = parents.get(current)
        paths.append(tuple(reversed(reverse_path)))
    return tuple(paths)


def chatgpt_records(
    source: Path, *, source_account: str | None = None
) -> Iterator[ConversationRecord]:
    """Stream ChatGPT official-export conversations and expand root-to-leaf branches."""

    with source.open("rb") as stream:
        for conversation_index, conversation in enumerate(ijson.items(stream, "item")):
            if not isinstance(conversation, Mapping):
                continue
            mapping = conversation.get("mapping")
            if not isinstance(mapping, Mapping):
                continue
            conversation_id = conversation.get("id") or conversation.get("conversation_id")
            source_thread_id = (
                conversation_id
                if isinstance(conversation_id, str)
                else f"conversation:{conversation_index}"
            )
            title = str(conversation.get("title") or "Imported ChatGPT conversation")
            for branch_index, path in enumerate(_branch_paths(mapping)):
                messages: list[ImportMessage] = []
                sidecars: list[InertSidecar] = []
                for node_id in path:
                    node = mapping.get(node_id)
                    if not isinstance(node, Mapping):
                        continue
                    message, sidecar = _chatgpt_message(node_id, node)
                    if message:
                        messages.append(message)
                    if sidecar:
                        sidecars.append(sidecar)
                if not messages:
                    continue
                yield ConversationRecord(
                    record_id=f"chatgpt:{source_thread_id}:{branch_index}",
                    source_type="chatgpt-official-export",
                    source_account=source_account,
                    source_thread_id=source_thread_id,
                    branch_path=path,
                    title=title if branch_index == 0 else f"{title} · branch {branch_index + 1}",
                    messages=tuple(messages),
                    sidecars=tuple(sidecars),
                )


def _codex_source_files(source: Path) -> tuple[Path, ...]:
    """Return a stable, symlink-free set of Codex rollout JSONL files."""

    if source.is_symlink():
        raise ImportError(f"refusing Codex import symlink: {source}")
    if source.is_file():
        if source.suffix.lower() != ".jsonl":
            raise ImportError("Codex import source must be a .jsonl file or directory")
        return (source,)
    if not source.is_dir():
        raise ImportError(f"Codex import source does not exist: {source}")
    files: list[Path] = []
    for candidate in source.rglob("*"):
        if candidate.is_symlink():
            raise ImportError(f"refusing symlink inside Codex import source: {candidate}")
        if candidate.is_file() and candidate.suffix.lower() == ".jsonl":
            files.append(candidate)
    if not files:
        raise ImportError("Codex import directory contains no .jsonl rollouts")
    return tuple(sorted(files, key=lambda path: path.relative_to(source).as_posix()))


def hash_import_source(source: Path) -> tuple[str, int]:
    """Hash either one export file or a deterministic Codex JSONL directory."""

    if source.is_file() or source.is_symlink():
        return hash_file(source)
    files = _codex_source_files(source)
    digest = hashlib.sha256()
    total_size = 0
    for path in files:
        relative = path.relative_to(source).as_posix().encode("utf-8")
        file_sha256, size = hash_file(path)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_sha256))
        digest.update(size.to_bytes(8, "big"))
        total_size += size
    return digest.hexdigest(), total_size


def _timestamp_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _rollout_message(
    payload: Mapping[str, Any], *, fallback_id: str, timestamp: Any
) -> ImportMessage | None:
    if payload.get("type") != "message" or payload.get("role") not in {"user", "assistant"}:
        return None
    text = _content_text(payload.get("content")).strip()
    if not text:
        return None
    source_id = payload.get("id")
    return ImportMessage(
        source_id=source_id if isinstance(source_id, str) else fallback_id,
        role=payload["role"],
        text=text,
        created_at=_timestamp_seconds(timestamp),
    )


def _codex_record(path: Path, *, source_account: str | None) -> ConversationRecord | None:
    session_id = path.stem
    cwd: str | None = None
    git_remote: str | None = None
    messages: list[ImportMessage] = []
    sidecars: list[InertSidecar] = []
    with path.open("rb") as stream:
        line_number = 0
        while line := stream.readline(MAX_CODEX_JSONL_LINE_BYTES + 1):
            line_number += 1
            if len(line) > MAX_CODEX_JSONL_LINE_BYTES:
                raise ImportError(f"Codex rollout line exceeds limit: {path}:{line_number}")
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ImportError(f"invalid Codex rollout JSON: {path}:{line_number}") from exc
            if not isinstance(event, Mapping):
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            event_type = event.get("type")
            if event_type == "session_meta":
                source_id = payload.get("id")
                if isinstance(source_id, str):
                    session_id = source_id
                source_cwd = payload.get("cwd")
                if isinstance(source_cwd, str):
                    cwd = source_cwd
                git = payload.get("git")
                if isinstance(git, Mapping):
                    remote = git.get("repository_url") or git.get("remote")
                    if isinstance(remote, str):
                        git_remote = remote
                continue
            if event_type == "turn_context":
                source_cwd = payload.get("cwd")
                if isinstance(source_cwd, str):
                    cwd = source_cwd
                continue
            if event_type == "response_item":
                fallback_id = f"{path.name}:{line_number}"
                message = _rollout_message(
                    payload,
                    fallback_id=fallback_id,
                    timestamp=event.get("timestamp"),
                )
                if message is not None:
                    messages.append(message)
                else:
                    sidecars.append(
                        InertSidecar(
                            source_id=fallback_id,
                            kind=f"codex:{payload.get('type', 'unknown')}",
                            payload={"source_line": line_number},
                        )
                    )
    if not messages:
        return None
    first_user = next((message.text for message in messages if message.role == "user"), "")
    title = " ".join(first_user.split())[:80] or f"Imported Codex task {session_id}"
    return ConversationRecord(
        record_id=f"codex-rollout:{session_id}:{hash_file(path)[0][:12]}",
        source_type="codex-rollout-jsonl",
        source_account=source_account,
        source_thread_id=session_id,
        title=title,
        messages=tuple(messages),
        sidecars=tuple(sidecars),
        suggested_cwd=cwd,
        suggested_git_remote=git_remote,
    )


def codex_records(
    source: Path, *, source_account: str | None = None
) -> Iterator[ConversationRecord]:
    """Parse another account's Codex rollouts without executing tool items."""

    for path in _codex_source_files(source):
        record = _codex_record(path, source_account=source_account)
        if record is not None:
            yield record


def record_from_backup_json(value: Any) -> ConversationRecord:
    if not isinstance(value, Mapping):
        raise ImportError("logical backup record must be an object")
    raw_source = value.get("source")
    source: Mapping[str, Any] = raw_source if isinstance(raw_source, Mapping) else {}
    thread_value = value.get("thread")
    if not isinstance(thread_value, Mapping):
        raise ImportError("logical backup record lacks thread")
    thread = ThreadSnapshot.model_validate(thread_value)
    messages: list[ImportMessage] = []
    sidecars: list[InertSidecar] = []
    for turn in thread.turns:
        for item in turn.items:
            if item.role in {"user", "assistant"} and item.text:
                messages.append(ImportMessage(source_id=item.id, role=item.role, text=item.text))
            elif item.text:
                sidecars.append(
                    InertSidecar(
                        source_id=item.id,
                        kind=f"codex:{item.kind.value}",
                        payload={"text": item.text, "metadata": item.metadata},
                    )
                )
    return ConversationRecord(
        record_id=f"csmbackup:{thread.id}",
        source_type="csmbackup",
        source_thread_id=str(source.get("thread_id") or thread.id),
        title=thread.title or f"Restored {thread.id}",
        messages=tuple(messages),
        sidecars=tuple(sidecars),
        suggested_cwd=thread.cwd,
        suggested_git_remote=thread.git_remote,
    )


def record_from_thread(snapshot: ThreadSnapshot) -> ConversationRecord:
    messages = tuple(
        ImportMessage(source_id=item.id, role=item.role, text=item.text)
        for turn in snapshot.turns
        for item in turn.items
        if item.role in {"user", "assistant"} and item.text
    )
    return ConversationRecord(
        record_id=f"codex:{snapshot.id}",
        source_type="codex-current-account",
        source_thread_id=snapshot.id,
        title=snapshot.title,
        messages=messages,
        suggested_cwd=snapshot.cwd,
        suggested_git_remote=snapshot.git_remote,
    )


def classify_record(
    record: ConversationRecord, existing: tuple[ConversationRecord, ...]
) -> tuple[ImportDisposition, tuple[str, ...]]:
    for other in existing:
        if record.content_fingerprint == other.content_fingerprint:
            return ImportDisposition.SKIP_EXACT, (f"exact duplicate of {other.record_id}",)
    for other in existing:
        if record.is_prefix_of(other):
            return ImportDisposition.SKIP_EXACT, (f"existing {other.record_id} is more complete",)
        if other.is_prefix_of(record):
            return ImportDisposition.PREFER_COMPLETE, (
                f"source extends existing {other.record_id}",
            )
    same_origin = [
        other
        for other in existing
        if other.source_thread_id and other.source_thread_id == record.source_thread_id
    ]
    if same_origin:
        return ImportDisposition.KEEP_DIVERGED, ("same source id diverged; keep both branches",)
    return ImportDisposition.CREATE, ("new logical conversation",)


class ImportPlanner:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def plan(
        self,
        *,
        source: Path,
        records: tuple[ConversationRecord, ...],
        existing: tuple[ConversationRecord, ...],
        capabilities: CapabilityMatrix,
        confirmed_cwd: str | None = None,
        confirmed_git_remote: str | None = None,
    ) -> ImportPlan:
        source_sha256, _ = hash_import_source(source)
        candidates: list[ImportCandidate] = []
        record_ids = [record.record_id for record in records]
        if len(record_ids) != len(set(record_ids)):
            raise ImportError("import source contains duplicate record ids")
        for index, record in enumerate(records):
            disposition: ImportDisposition
            reasons: tuple[str, ...]
            exact_predecessor = next(
                (
                    other
                    for other in records[:index]
                    if record.content_fingerprint == other.content_fingerprint
                ),
                None,
            )
            more_complete = next(
                (
                    other
                    for other_index, other in enumerate(records)
                    if other_index != index
                    and record.is_prefix_of(other)
                    and not other.is_prefix_of(record)
                ),
                None,
            )
            if exact_predecessor is not None:
                disposition = ImportDisposition.SKIP_EXACT
                reasons = (f"same import batch duplicates {exact_predecessor.record_id}",)
            elif more_complete is not None:
                disposition = ImportDisposition.SKIP_EXACT
                reasons = (f"same import batch contains more complete {more_complete.record_id}",)
            else:
                disposition, reasons = classify_record(record, existing)
            suggested_cwd = confirmed_cwd or record.suggested_cwd
            mapping_confirmed = confirmed_cwd is not None
            if disposition not in {ImportDisposition.SKIP_EXACT} and not mapping_confirmed:
                disposition = ImportDisposition.QUARANTINE
                reasons = (*reasons, "project mapping not confirmed; route to quarantine")
            candidates.append(
                ImportCandidate(
                    candidate_id=record.record_id,
                    source_type=record.source_type,
                    source_account=record.source_account,
                    source_thread_id=record.source_thread_id,
                    branch_path=record.branch_path,
                    title=record.title,
                    fingerprint=record.content_fingerprint,
                    disposition=disposition,
                    mapped_cwd=suggested_cwd,
                    mapped_git_remote=confirmed_git_remote or record.suggested_git_remote,
                    mapping_confirmed=mapping_confirmed,
                    reasons=reasons,
                )
            )
        draft = ImportPlan(
            plan_id=str(uuid4()),
            created_at=utc_now(),
            source_sha256=source_sha256,
            capability_fingerprint=capabilities.fingerprint,
            candidates=tuple(candidates),
        )
        return draft.seal()


def _injected_items(record: ConversationRecord, candidate: ImportCandidate) -> list[dict[str, Any]]:
    provenance = {
        "type": "codex-session-manager-import",
        "source_type": record.source_type,
        "source_account": record.source_account,
        "source_thread_id": record.source_thread_id,
        "branch_path": record.branch_path,
        "source_fingerprint": record.content_fingerprint,
        "inert_sidecar_count": len(record.sidecars),
        "tool_calls_replayed": False,
    }
    items: list[dict[str, Any]] = [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "CSM import manifest\n"
                    + json.dumps(provenance, ensure_ascii=False, sort_keys=True),
                }
            ],
        }
    ]
    for message in record.messages:
        content_type = "input_text" if message.role == "user" else "output_text"
        items.append(
            {
                "type": "message",
                "role": message.role,
                "content": [{"type": content_type, "text": message.text}],
            }
        )
    return items


class LogicalImportExecutor:
    """Create new threads and inject inert logical history; never start a model turn."""

    def __init__(
        self,
        *,
        client: SubprocessAppServer,
        capabilities: CapabilityMatrix,
        paths: AppPaths,
        audit: AuditStore,
    ) -> None:
        self.client = client
        self.capabilities = capabilities
        self.paths = paths
        self.audit = audit

    def apply(
        self,
        plan: ImportPlan,
        *,
        source: Path,
        records: tuple[ConversationRecord, ...],
    ) -> dict[str, str]:
        plan.verify()
        if plan.capability_fingerprint != self.capabilities.fingerprint:
            raise ImportError("App Server capability drift invalidated the import plan")
        self.capabilities.require_write("thread/start")
        self.capabilities.require_write("thread/inject_items")
        self.capabilities.require_write("thread/name/set")
        source_sha256, _ = hash_import_source(source)
        if source_sha256 != plan.source_sha256:
            raise ImportError("import source changed after planning")
        records_by_id = {record.record_id: record for record in records}
        quarantine = self.paths.imports_dir / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
        created: dict[str, str] = {}
        self.audit.begin_operation(plan_sha256=plan.plan_sha256, action="import")
        try:
            for candidate in plan.candidates:
                if candidate.disposition is ImportDisposition.SKIP_EXACT:
                    continue
                record = records_by_id.get(candidate.candidate_id)
                if record is None or record.content_fingerprint != candidate.fingerprint:
                    raise ImportError(f"record drift for {candidate.candidate_id}")
                if (
                    record.source_type != candidate.source_type
                    or record.source_account != candidate.source_account
                    or record.source_thread_id != candidate.source_thread_id
                    or record.branch_path != candidate.branch_path
                    or record.title != candidate.title
                ):
                    raise ImportError(f"record provenance drift for {candidate.candidate_id}")
                cwd = candidate.mapped_cwd if candidate.mapping_confirmed else str(quarantine)
                thread = self.client.start_thread(cwd=cwd, name=candidate.title)
                thread_id = thread.get("id")
                if not isinstance(thread_id, str):
                    raise ImportError("thread/start returned no id")
                injected = _injected_items(record, candidate)
                self.client.inject_items(thread_id, injected)
                reread = self.client.read_thread(thread_id, include_turns=True)
                if reread.get("id") != thread_id:
                    raise ImportError(f"post-injection read failed for {thread_id}")
                expected_messages = tuple(
                    (
                        str(item["role"]),
                        str(item["content"][0]["text"]),
                    )
                    for item in injected
                )
                observed_messages = model_visible_messages(reread)
                if observed_messages[-len(expected_messages) :] != expected_messages:
                    raise ImportError(
                        f"post-injection ordered-message verification failed for {thread_id}"
                    )
                created[candidate.candidate_id] = thread_id
            self.audit.finish_operation(plan_sha256=plan.plan_sha256, status="succeeded")
            self.audit.append(
                event_type="import.apply",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(created.values()),
                details={"created_count": len(created), "source_sha256": source_sha256},
            )
            return created
        except BaseException as exc:
            self.audit.finish_operation(
                plan_sha256=plan.plan_sha256, status="failed", error=str(exc)
            )
            self.audit.append(
                event_type="import.apply",
                actor="human",
                result="failed",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(created.values()),
                details={"error": str(exc), "created_count": len(created)},
            )
            raise
