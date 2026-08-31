"""App Server response normalization, graph expansion, and local filtering."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from codex_session_manager.app_server import SubprocessAppServer
from codex_session_manager.hashing import estimate_tokens, fingerprint
from codex_session_manager.models import (
    ItemKind,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TurnSnapshot,
)

_AUDITED_THREAD_FIELDS = frozenset(
    {
        "agentNickname",
        "agentRole",
        "cliVersion",
        "createdAt",
        "cwd",
        "ephemeral",
        "forkedFromId",
        "gitInfo",
        "id",
        "modelProvider",
        "name",
        "parentThreadId",
        "path",
        "preview",
        "recencyAt",
        "sessionId",
        "source",
        "status",
        "threadSource",
        "turns",
        "updatedAt",
    }
)
# Compatibility aliases observed in older App Server payloads.  They remain
# explicit so a genuinely new top-level field still disables lineage writes.
_THREAD_COMPATIBILITY_ALIASES = frozenset(
    {
        "archived",
        "gitRemote",
        "isPinned",
        "parentId",
        "pinned",
        "sourceKind",
        "title",
    }
)


class InventoryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cwd: str | None = None
    git_remote: str | None = None
    source_kinds: tuple[str, ...] = ()
    archived: bool | None = None
    pinned: bool | None = None
    statuses: tuple[ThreadStatus, ...] = ()
    updated_before: datetime | None = None
    updated_after: datetime | None = None
    minimum_size: int | None = None
    maximum_size: int | None = None
    parent_id: str | None = None
    search: str | None = None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _status(value: Any) -> ThreadStatus:
    status_type = value.get("type") if isinstance(value, Mapping) else value
    if not isinstance(status_type, str):
        return ThreadStatus.UNKNOWN
    try:
        return ThreadStatus(status_type)
    except (TypeError, ValueError):
        return ThreadStatus.UNKNOWN


def _text_from(value: Any) -> str:
    fragments: list[str] = []

    def add_structured(node: Any) -> None:
        if not node:
            return
        try:
            encoded = json.dumps(
                node,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return
        if encoded:
            fragments.append(encoded)

    def visit(node: Any) -> None:
        if isinstance(node, str):
            fragments.append(node)
        elif isinstance(node, Mapping):
            for key in (
                "text",
                "outputText",
                "inputText",
                "message",
                "summary",
                "aggregatedOutput",
                "command",
                "query",
                "prompt",
                "revisedPrompt",
                "output",
                "path",
                "tool",
            ):
                child = node.get(key)
                if isinstance(child, str):
                    fragments.append(child)
                elif isinstance(child, (list, tuple)):
                    visit(child)
            for key in (
                "arguments",
                "changes",
                "result",
                "error",
                "contentItems",
                "commandActions",
                "payload",
            ):
                child = node.get(key)
                if isinstance(child, str):
                    fragments.append(child)
                elif isinstance(child, (Mapping, list, tuple)):
                    add_structured(child)
            content = node.get("content")
            if isinstance(content, (list, tuple)):
                for child in content:
                    visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(value)
    deduplicated: list[str] = []
    for fragment in fragments:
        if fragment and (not deduplicated or deduplicated[-1] != fragment):
            deduplicated.append(fragment)
    return "\n".join(deduplicated)


def _message_role(raw_type: str, role: str | None) -> str | None:
    """Infer message roles from App Server's role-less message item types."""

    if role in {"user", "assistant", "developer", "system"}:
        return role
    normalized = raw_type.lower().replace("_", "").replace("-", "")
    if normalized in {"user", "usermessage"}:
        return "user"
    if normalized in {"assistant", "assistantmessage", "agentmessage"}:
        return "assistant"
    if normalized in {"developer", "developermessage"}:
        return "developer"
    if normalized in {"system", "systemmessage"}:
        return "system"
    return role


def _item_kind(raw_type: str, role: str | None) -> ItemKind:
    normalized = raw_type.lower().replace("_", "").replace("-", "")
    if "reason" in normalized:
        return ItemKind.REASONING
    if "filechange" in normalized or "patch" in normalized:
        return ItemKind.FILE_CHANGE
    if "verification" in normalized or "validation" in normalized or "testresult" in normalized:
        return ItemKind.VERIFICATION
    if "approval" in normalized or "permission" in normalized:
        return ItemKind.APPROVAL
    if "error" in normalized:
        return ItemKind.ERROR
    if "tool" in normalized or "command" in normalized or "mcp" in normalized:
        if "result" in normalized or "output" in normalized:
            return ItemKind.TOOL_RESULT
        return ItemKind.TOOL_CALL
    if "summary" in normalized:
        return ItemKind.SUMMARY
    if "message" in normalized or role:
        if role == "user":
            return ItemKind.USER_MESSAGE
        if role == "assistant":
            return ItemKind.ASSISTANT_MESSAGE
        if role == "developer":
            return ItemKind.DEVELOPER_MESSAGE
        if role == "system":
            return ItemKind.SYSTEM_MESSAGE
    return ItemKind.UNKNOWN


def _normalized_item(raw: Mapping[str, Any], turn_id: str, index: int) -> ThreadItemSnapshot:
    raw_type = str(raw.get("type") or raw.get("kind") or "unknown")
    role_value = raw.get("role")
    raw_role = role_value if isinstance(role_value, str) else None
    role = _message_role(raw_type, raw_role)
    kind = _item_kind(raw_type, role)
    item_id_value = raw.get("id") or raw.get("itemId")
    item_id = (
        item_id_value
        if isinstance(item_id_value, str) and item_id_value
        else f"{turn_id}:item:{index}:{fingerprint(dict(raw))[:12]}"
    )
    text = _text_from(raw)
    reasons: list[str] = []
    if kind in {
        ItemKind.DEVELOPER_MESSAGE,
        ItemKind.SYSTEM_MESSAGE,
        ItemKind.VERIFICATION,
        ItemKind.APPROVAL,
        ItemKind.ERROR,
        ItemKind.UNKNOWN,
    }:
        reasons.append(f"hard-protected item kind: {kind.value}")
    depends_value = raw.get("dependsOn") or raw.get("depends_on") or []
    depends_on = (
        tuple(value for value in depends_value if isinstance(value, str))
        if isinstance(depends_value, list)
        else ()
    )
    metadata: dict[str, Any] = {
        "raw_keys": sorted(str(key) for key in raw),
        # Bind plans to every protocol field, including future/opaque payloads,
        # without copying potentially large or sensitive raw objects into CSM.
        "raw_payload_sha256": fingerprint(dict(raw)),
    }
    call_id = raw.get("callId") or raw.get("call_id")
    if isinstance(call_id, str):
        metadata["call_id"] = call_id
    return ThreadItemSnapshot(
        id=item_id,
        turn_id=turn_id,
        kind=kind,
        raw_type=raw_type,
        role=role,
        text=text,
        created_at=_timestamp(raw.get("createdAt") or raw.get("created_at")),
        token_estimate=estimate_tokens(text),
        depends_on=depends_on,
        hard_protected=bool(reasons),
        protected_reasons=tuple(reasons),
        metadata=metadata,
    )


def _normalized_turn(raw: Mapping[str, Any], index: int, *, thread_active: bool) -> TurnSnapshot:
    turn_id_value = raw.get("id") or raw.get("turnId")
    turn_id = turn_id_value if isinstance(turn_id_value, str) else f"turn:{index}"
    raw_items = raw.get("items")
    items: list[ThreadItemSnapshot] = []
    if isinstance(raw_items, list):
        items = [
            _normalized_item(item, turn_id, item_index)
            for item_index, item in enumerate(raw_items)
            if isinstance(item, Mapping)
        ]
    tool_groups: dict[str, set[ItemKind]] = defaultdict(set)
    for item in items:
        call_id = item.metadata.get("call_id")
        if item.kind in {ItemKind.TOOL_CALL, ItemKind.TOOL_RESULT} and isinstance(call_id, str):
            tool_groups[call_id].add(item.kind)
    normalized_items: list[ThreadItemSnapshot] = []
    for item in items:
        if item.kind not in {ItemKind.TOOL_CALL, ItemKind.TOOL_RESULT}:
            normalized_items.append(item)
            continue
        call_id = item.metadata.get("call_id")
        paired = isinstance(call_id, str) and tool_groups.get(call_id) == {
            ItemKind.TOOL_CALL,
            ItemKind.TOOL_RESULT,
        }
        if paired:
            normalized_items.append(item)
            continue
        normalized_items.append(
            item.model_copy(
                update={
                    "hard_protected": True,
                    "protected_reasons": tuple(
                        dict.fromkeys(
                            (
                                *item.protected_reasons,
                                "unpaired tool item lacks a complete call/result group",
                            )
                        )
                    ),
                }
            )
        )
    items = normalized_items
    status = str(raw.get("status") or "unknown")
    in_progress = thread_active or status.lower() in {"inprogress", "active", "running"}
    if in_progress:
        items = [
            item.model_copy(
                update={
                    "hard_protected": True,
                    "protected_reasons": tuple(
                        dict.fromkeys((*item.protected_reasons, "turn is still in progress"))
                    ),
                }
            )
            for item in items
        ]
    return TurnSnapshot(
        id=turn_id,
        status=status,
        started_at=_timestamp(raw.get("startedAt") or raw.get("createdAt")),
        completed_at=_timestamp(raw.get("completedAt")),
        items=tuple(items),
    )


def _protect_current_request(turns: tuple[TurnSnapshot, ...]) -> tuple[TurnSnapshot, ...]:
    # Keep the indexes as scalar sentinels instead of unpacking an optional
    # tuple.  Besides being easier to audit, this tolerates partially decoded
    # App Server payloads in standalone/Nuitka builds.
    latest_turn_index = -1
    latest_item_index = -1
    for turn_index, turn in enumerate(turns):
        for item_index, item in enumerate(turn.items):
            if item.kind is ItemKind.USER_MESSAGE:
                latest_turn_index = turn_index
                latest_item_index = item_index
    if latest_turn_index < 0 or latest_item_index < 0:
        return turns
    turn = turns[latest_turn_index]
    item = turn.items[latest_item_index]
    protected = item.model_copy(
        update={
            "hard_protected": True,
            "protected_reasons": tuple(
                dict.fromkeys((*(item.protected_reasons or ()), "current user request"))
            ),
        }
    )
    new_items = list(turn.items)
    new_items[latest_item_index] = protected
    new_turns = list(turns)
    new_turns[latest_turn_index] = turn.model_copy(update={"items": tuple(new_items)})
    return tuple(new_turns)


def normalize_thread(
    raw: Mapping[str, Any],
    *,
    archived: bool | None = None,
    content_complete: bool = False,
) -> ThreadSnapshot:
    """Normalize one official App Server thread object."""

    thread_id = raw.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread object lacks a non-empty id")
    status = _status(raw.get("status"))
    raw_turns = raw.get("turns")
    turns_shape_complete = isinstance(raw_turns, list) and all(
        isinstance(turn, Mapping)
        and isinstance(turn.get("items"), list)
        and all(isinstance(item, Mapping) for item in turn["items"])
        for turn in raw_turns
    )
    turns: tuple[TurnSnapshot, ...] = ()
    if isinstance(raw_turns, list):
        turns = tuple(
            _normalized_turn(turn, index, thread_active=status is ThreadStatus.ACTIVE)
            for index, turn in enumerate(raw_turns)
            if isinstance(turn, Mapping)
        )
        turns = _protect_current_request(turns)
    raw_git_info = raw.get("gitInfo")
    git_info: Mapping[str, Any] = raw_git_info if isinstance(raw_git_info, Mapping) else {}
    git_remote_value = (
        git_info.get("repositoryUrl") or git_info.get("remoteUrl") or raw.get("gitRemote")
    )
    raw_path_value = raw.get("path")
    raw_path = raw_path_value if isinstance(raw_path_value, str) else None
    size_bytes = 0
    if raw_path:
        path = Path(raw_path)
        try:
            if path.is_file() and not path.is_symlink():
                size_bytes = path.stat().st_size
        except OSError:
            pass
    source_value = raw.get("sourceKind") or raw.get("source") or "unknown"
    if isinstance(source_value, Mapping):
        source_kind = str(source_value.get("type") or "unknown")
    else:
        source_kind = str(source_value)
    parent_value = raw.get("parentThreadId") or raw.get("parentId")
    parent_id = parent_value if isinstance(parent_value, str) else None
    unknown_item_count = sum(item.kind is ItemKind.UNKNOWN for turn in turns for item in turn.items)
    unknown_thread_fields = set(raw) - _AUDITED_THREAD_FIELDS - _THREAD_COMPATIBILITY_ALIASES
    return ThreadSnapshot(
        id=thread_id,
        title=str(raw.get("name") or raw.get("title") or ""),
        preview=str(raw.get("preview") or ""),
        cwd=raw.get("cwd") if isinstance(raw.get("cwd"), str) else None,
        git_remote=git_remote_value if isinstance(git_remote_value, str) else None,
        source_kind=source_kind,
        model_provider=(
            raw.get("modelProvider") if isinstance(raw.get("modelProvider"), str) else None
        ),
        created_at=_timestamp(raw.get("createdAt")),
        updated_at=_timestamp(raw.get("updatedAt")),
        status=status,
        archived=bool(raw.get("archived", archived if archived is not None else False)),
        pinned=bool(raw.get("isPinned", raw.get("pinned", False))),
        ephemeral=bool(raw.get("ephemeral", False)),
        parent_id=parent_id,
        session_id=raw.get("sessionId") if isinstance(raw.get("sessionId"), str) else None,
        forked_from_id=(
            raw.get("forkedFromId") if isinstance(raw.get("forkedFromId"), str) else None
        ),
        turns=turns,
        content_complete=content_complete and turns_shape_complete,
        size_bytes=size_bytes,
        raw_path=raw_path,
        mapping_complete=not unknown_thread_fields,
        unknown_item_count=unknown_item_count,
    )


def model_visible_messages(raw_thread: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return the exact ordered user/assistant message projection from a reread."""

    snapshot = normalize_thread(raw_thread, content_complete=True)
    return tuple(
        (item.role, item.text)
        for turn in snapshot.turns
        for item in turn.items
        if item.role in {"user", "assistant"} and item.text
    )


def attach_descendant_closures(
    snapshots: Iterable[ThreadSnapshot],
) -> tuple[ThreadSnapshot, ...]:
    snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    children: dict[str, set[str]] = defaultdict(set)
    for snapshot in snapshots_by_id.values():
        for parent in _parent_ids(snapshot):
            if parent in snapshots_by_id:
                children[parent].add(snapshot.id)

    def has_cycle(root_id: str) -> bool:
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(thread_id: str) -> bool:
            if thread_id in visiting:
                return True
            if thread_id in visited:
                return False
            visiting.add(thread_id)
            if any(visit(child) for child in children.get(thread_id, ())):
                return True
            visiting.remove(thread_id)
            visited.add(thread_id)
            return False

        return visit(root_id)

    normalized: list[ThreadSnapshot] = []
    for snapshot in snapshots_by_id.values():
        closure: list[str] = []
        queue_: deque[str] = deque(sorted(children.get(snapshot.id, ())))
        seen: set[str] = {snapshot.id}
        while queue_:
            child = queue_.popleft()
            if child in seen:
                continue
            seen.add(child)
            closure.append(child)
            queue_.extend(sorted(children.get(child, ())))
        closure_with_root = {snapshot.id, *closure}
        missing_parent = any(
            parent not in snapshots_by_id
            for thread_id in closure_with_root
            for parent in _parent_ids(snapshots_by_id[thread_id])
        )
        inherited_incomplete = any(
            not snapshots_by_id[thread_id].mapping_complete for thread_id in closure_with_root
        )
        mapping_complete = (
            snapshot.mapping_complete
            and not missing_parent
            and not inherited_incomplete
            and not has_cycle(snapshot.id)
        )
        normalized.append(
            snapshot.model_copy(
                update={
                    "spawned_descendant_ids": tuple(closure),
                    "mapping_complete": mapping_complete,
                }
            )
        )
    return tuple(sorted(normalized, key=lambda item: item.id))


def _parent_ids(snapshot: ThreadSnapshot) -> tuple[str, ...]:
    """Return both independent lineage edges without duplicates."""

    return tuple(
        dict.fromkeys(
            parent for parent in (snapshot.parent_id, snapshot.forked_from_id) if parent is not None
        )
    )


def matches_filter(snapshot: ThreadSnapshot, criteria: InventoryFilter) -> bool:
    if criteria.cwd and snapshot.cwd != criteria.cwd:
        return False
    if criteria.git_remote and snapshot.git_remote != criteria.git_remote:
        return False
    if criteria.source_kinds and snapshot.source_kind not in criteria.source_kinds:
        return False
    if criteria.archived is not None and snapshot.archived is not criteria.archived:
        return False
    if criteria.pinned is not None and snapshot.pinned is not criteria.pinned:
        return False
    if criteria.statuses and snapshot.status not in criteria.statuses:
        return False
    if criteria.updated_before and (
        snapshot.updated_at is None or snapshot.updated_at >= criteria.updated_before
    ):
        return False
    if criteria.updated_after and (
        snapshot.updated_at is None or snapshot.updated_at <= criteria.updated_after
    ):
        return False
    if criteria.minimum_size is not None and snapshot.size_bytes < criteria.minimum_size:
        return False
    if criteria.maximum_size is not None and snapshot.size_bytes > criteria.maximum_size:
        return False
    if criteria.parent_id and criteria.parent_id not in _parent_ids(snapshot):
        return False
    if criteria.search:
        haystack = f"{snapshot.id}\n{snapshot.title}\n{snapshot.preview}".casefold()
        if criteria.search.casefold() not in haystack:
            return False
    return True


def merge_thread_detail(summary: ThreadSnapshot, detail: ThreadSnapshot) -> ThreadSnapshot:
    """Preserve list-only management and lineage fields during a deep read."""

    if summary.id != detail.id:
        raise ValueError("cannot merge thread snapshots with different ids")
    return detail.model_copy(
        update={
            "title": detail.title or summary.title,
            "preview": detail.preview or summary.preview,
            "cwd": detail.cwd or summary.cwd,
            "git_remote": detail.git_remote or summary.git_remote,
            "source_kind": (
                detail.source_kind if detail.source_kind != "unknown" else summary.source_kind
            ),
            "model_provider": detail.model_provider or summary.model_provider,
            "created_at": detail.created_at or summary.created_at,
            "updated_at": detail.updated_at or summary.updated_at,
            "archived": summary.archived,
            "pinned": detail.pinned or summary.pinned,
            "ephemeral": detail.ephemeral or summary.ephemeral,
            "parent_id": detail.parent_id or summary.parent_id,
            "session_id": detail.session_id or summary.session_id,
            "forked_from_id": detail.forked_from_id or summary.forked_from_id,
            "spawned_descendant_ids": summary.spawned_descendant_ids,
            "raw_path": detail.raw_path or summary.raw_path,
            "size_bytes": detail.size_bytes or summary.size_bytes,
            "mapping_complete": summary.mapping_complete and detail.mapping_complete,
        }
    )


class InventoryService:
    """Read normalized active and archived threads through App Server."""

    def __init__(self, client: SubprocessAppServer) -> None:
        self.client = client

    def list(
        self,
        *,
        criteria: InventoryFilter | None = None,
        include_active: bool = True,
        include_archived: bool = True,
        include_turns: bool = False,
    ) -> tuple[ThreadSnapshot, ...]:
        snapshots: list[ThreadSnapshot] = []
        for enabled, archived in (
            (include_active, False),
            (include_archived, True),
        ):
            if not enabled:
                continue
            for raw in self.client.list_threads(archived=archived):
                summary = normalize_thread(raw, archived=archived)
                source = raw.get("sourceKind") or raw.get("source")
                is_subagent = (isinstance(source, str) and source.startswith("subAgent")) or (
                    isinstance(source, Mapping) and "subAgent" in source
                )
                if not include_turns and is_subagent and summary.parent_id is None:
                    detail = normalize_thread(
                        self.client.read_thread(summary.id, include_turns=False),
                        archived=archived,
                    )
                    summary = merge_thread_detail(summary, detail)
                    if summary.parent_id is None and summary.forked_from_id is None:
                        summary = summary.model_copy(update={"mapping_complete": False})
                snapshots.append(summary)
        deduplicated = {snapshot.id: snapshot for snapshot in snapshots}
        if include_turns:
            detailed: dict[str, ThreadSnapshot] = {}
            for summary in deduplicated.values():
                raw = self.client.read_thread(summary.id, include_turns=True)
                detail = normalize_thread(
                    raw,
                    archived=summary.archived,
                    content_complete=True,
                )
                detailed[summary.id] = merge_thread_detail(summary, detail)
            deduplicated = detailed
        with_closures = attach_descendant_closures(deduplicated.values())
        if criteria is None:
            return with_closures
        return tuple(item for item in with_closures if matches_filter(item, criteria))

    def hydrate(
        self,
        summaries: tuple[ThreadSnapshot, ...],
        thread_ids: tuple[str, ...],
    ) -> tuple[ThreadSnapshot, ...]:
        """Deep-read only requested IDs while preserving the global lineage index."""

        summaries = attach_descendant_closures(summaries)
        by_id = {snapshot.id: snapshot for snapshot in summaries}
        requested = tuple(dict.fromkeys(thread_ids))
        missing = [thread_id for thread_id in requested if thread_id not in by_id]
        if missing:
            raise ValueError("threads are no longer available: " + ", ".join(sorted(missing)))
        merged = dict(by_id)
        for thread_id in requested:
            summary = by_id[thread_id]
            raw = self.client.read_thread(thread_id, include_turns=True)
            detail = normalize_thread(
                raw,
                archived=summary.archived,
                content_complete=True,
            )
            merged[thread_id] = merge_thread_detail(summary, detail)
        return attach_descendant_closures(merged.values())

    def list_for_targets(
        self,
        target_ids: tuple[str, ...],
        *,
        include_active: bool = True,
        include_archived: bool = True,
    ) -> tuple[ThreadSnapshot, ...]:
        """Build the full lineage index, then deep-read selected descendant closures."""

        summaries = self.list(
            include_active=include_active,
            include_archived=include_archived,
            include_turns=False,
        )
        closure_ids = target_closure_ids(summaries, target_ids)
        return self.hydrate(summaries, closure_ids)

    def read(self, thread_id: str, *, include_turns: bool = True) -> ThreadSnapshot:
        raw = self.client.read_thread(thread_id, include_turns=include_turns)
        return normalize_thread(raw, content_complete=include_turns)


def target_closure_ids(
    snapshots: tuple[ThreadSnapshot, ...],
    target_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Resolve selected roots to a deterministic union of descendant closures."""

    by_id = {snapshot.id: snapshot for snapshot in attach_descendant_closures(snapshots)}
    requested = tuple(dict.fromkeys(target_ids))
    if not requested:
        raise ValueError("at least one thread must be selected")
    missing = [thread_id for thread_id in requested if thread_id not in by_id]
    if missing:
        raise ValueError("threads are no longer available: " + ", ".join(sorted(missing)))
    closure: set[str] = set()
    for thread_id in requested:
        snapshot = by_id[thread_id]
        closure.update((snapshot.id, *snapshot.spawned_descendant_ids))
    return tuple(sorted(closure))
