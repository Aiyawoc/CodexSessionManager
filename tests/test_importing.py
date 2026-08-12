from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_session_manager.audit import AuditStore
from codex_session_manager.importing import (
    ConversationRecord,
    ImportMessage,
    ImportPlanner,
    LogicalImportExecutor,
    _injected_items,
    chatgpt_records,
    classify_record,
    codex_records,
    hash_import_source,
)
from codex_session_manager.importing import (
    ImportError as CsmImportError,
)
from codex_session_manager.models import (
    ImportCandidate,
    ImportDisposition,
)


def _write_export(path: Path) -> None:
    export = [
        {
            "id": "conversation-1",
            "title": "Branches",
            "mapping": {
                "root": {"parent": None, "children": ["user"], "message": None},
                "user": {
                    "parent": "root",
                    "children": ["a1", "tool"],
                    "message": {
                        "id": "m-user",
                        "author": {"role": "user"},
                        "content": {"parts": ["question"]},
                    },
                },
                "a1": {
                    "parent": "user",
                    "children": [],
                    "message": {
                        "id": "m-a1",
                        "author": {"role": "assistant"},
                        "content": {"parts": ["answer one"]},
                    },
                },
                "tool": {
                    "parent": "user",
                    "children": ["a2"],
                    "message": {
                        "id": "m-tool",
                        "author": {"role": "tool"},
                        "content": {"result": "do not execute"},
                    },
                },
                "a2": {
                    "parent": "tool",
                    "children": [],
                    "message": {
                        "id": "m-a2",
                        "author": {"role": "assistant"},
                        "content": {"parts": ["answer two"]},
                    },
                },
            },
        }
    ]
    path.write_text(json.dumps(export), encoding="utf-8")


def test_chatgpt_export_expands_branches_and_keeps_tools_inert(tmp_path: Path) -> None:
    source = tmp_path / "conversations.json"
    _write_export(source)
    records = tuple(chatgpt_records(source, source_account="other@example.test"))
    assert len(records) == 2
    assert {record.messages[-1].text for record in records} == {"answer one", "answer two"}
    second = next(record for record in records if record.messages[-1].text == "answer two")
    assert second.sidecars[0].kind == "chatgpt:tool"
    assert second.sidecars[0].execute is False

    candidate = ImportCandidate(
        candidate_id=second.record_id,
        source_type=second.source_type,
        fingerprint=second.content_fingerprint,
        disposition=ImportDisposition.CREATE,
        mapping_confirmed=True,
    )
    items = _injected_items(second, candidate)
    encoded = json.dumps(items, ensure_ascii=False)
    assert "do not execute" not in encoded
    assert '"tool_calls_replayed": false' in items[0]["content"][0]["text"]


def test_dedupe_exact_prefix_and_divergence() -> None:
    base = ConversationRecord(
        record_id="base",
        source_type="test",
        source_thread_id="origin",
        messages=(ImportMessage(source_id="1", role="user", text="one"),),
    )
    complete = base.model_copy(
        update={
            "record_id": "complete",
            "messages": (
                *base.messages,
                ImportMessage(source_id="2", role="assistant", text="two"),
            ),
        }
    )
    diverged = base.model_copy(
        update={
            "record_id": "diverged",
            "messages": (
                *base.messages,
                ImportMessage(source_id="3", role="assistant", text="different"),
            ),
        }
    )
    assert classify_record(base, (base,))[0] is ImportDisposition.SKIP_EXACT
    assert classify_record(complete, (base,))[0] is ImportDisposition.PREFER_COMPLETE
    assert classify_record(base, (complete,))[0] is ImportDisposition.SKIP_EXACT
    assert classify_record(diverged, (complete,))[0] is ImportDisposition.KEEP_DIVERGED


def test_import_plan_quarantines_unconfirmed_project_mapping(
    tmp_path: Path, app_paths, capabilities
) -> None:
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    record = ConversationRecord(
        record_id="new",
        source_type="test",
        messages=(ImportMessage(source_id="1", role="user", text="hello"),),
        suggested_cwd="/untrusted/project",
    )
    plan = ImportPlanner(app_paths).plan(
        source=source,
        records=(record,),
        existing=(),
        capabilities=capabilities,
    )
    plan.verify()
    assert plan.candidates[0].disposition is ImportDisposition.QUARANTINE
    assert plan.candidates[0].mapping_confirmed is False


def test_import_plan_deduplicates_exact_and_prefix_records_within_batch(
    tmp_path: Path, app_paths, capabilities
) -> None:
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    short = ConversationRecord(
        record_id="short",
        source_type="test",
        messages=(ImportMessage(source_id="1", role="user", text="hello"),),
    )
    duplicate = short.model_copy(update={"record_id": "duplicate"})
    complete = short.model_copy(
        update={
            "record_id": "complete",
            "messages": (
                *short.messages,
                ImportMessage(source_id="2", role="assistant", text="answer"),
            ),
        }
    )
    plan = ImportPlanner(app_paths).plan(
        source=source,
        records=(short, duplicate, complete),
        existing=(),
        capabilities=capabilities,
        confirmed_cwd="/confirmed",
    )
    dispositions = {candidate.candidate_id: candidate.disposition for candidate in plan.candidates}
    assert dispositions == {
        "short": ImportDisposition.SKIP_EXACT,
        "duplicate": ImportDisposition.SKIP_EXACT,
        "complete": ImportDisposition.CREATE,
    }


def test_chatgpt_cycle_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "cycle.json"
    source.write_text(
        json.dumps(
            [
                {
                    "mapping": {
                        "a": {"parent": "b", "children": ["b"]},
                        "b": {"parent": "a", "children": ["a"]},
                    }
                }
            ]
        ),
        encoding="utf-8",
    )
    # A pure cycle has no leaf and therefore imports nothing rather than
    # inventing a linearized conversation.
    assert tuple(chatgpt_records(source)) == ()


def _write_codex_rollout(path: Path, *, session_id: str = "other-thread") -> None:
    events = (
        {
            "timestamp": "2026-08-11T01:02:03Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/other/account/project",
                "git": {"repository_url": "https://example.test/repo.git"},
            },
        },
        {
            "timestamp": "2026-08-11T01:03:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "please inspect"}],
            },
        },
        {
            "timestamp": "2026-08-11T01:04:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "dangerous_tool",
                "arguments": "do not replay",
            },
        },
        {
            "timestamp": "2026-08-11T01:05:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "inspection complete"}],
            },
        },
    )
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def test_codex_rollout_import_is_logical_and_tools_stay_inert(tmp_path: Path) -> None:
    source = tmp_path / "sessions" / "2026" / "08" / "11"
    source.mkdir(parents=True)
    rollout = source / "rollout.jsonl"
    _write_codex_rollout(rollout)

    records = tuple(codex_records(tmp_path / "sessions", source_account="old-account"))
    assert len(records) == 1
    record = records[0]
    assert record.source_thread_id == "other-thread"
    assert [message.text for message in record.messages] == [
        "please inspect",
        "inspection complete",
    ]
    assert record.sidecars[0].kind == "codex:function_call"
    assert record.sidecars[0].execute is False
    candidate = ImportCandidate(
        candidate_id=record.record_id,
        source_type=record.source_type,
        source_account=record.source_account,
        source_thread_id=record.source_thread_id,
        fingerprint=record.content_fingerprint,
        disposition=ImportDisposition.CREATE,
        mapping_confirmed=True,
    )
    assert "do not replay" not in json.dumps(_injected_items(record, candidate))


def test_codex_directory_hash_binds_paths_and_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "rollouts"
    source.mkdir()
    _write_codex_rollout(source / "one.jsonl")
    first, size = hash_import_source(source)
    assert size > 0
    (source / "one.jsonl").rename(source / "renamed.jsonl")
    second, _ = hash_import_source(source)
    assert first != second
    (source / "linked.jsonl").symlink_to(source / "renamed.jsonl")
    with pytest.raises(CsmImportError, match="symlink"):
        tuple(codex_records(source))


class _ImportClient:
    def __init__(self, *, preserve_injection: bool = True) -> None:
        self.preserve_injection = preserve_injection
        self.items: list[dict[str, object]] = []

    def start_thread(self, *, cwd: str | None = None, name: str | None = None):
        assert cwd == "/confirmed/project"
        assert name == "Imported task"
        return {"id": "derived-import"}

    def inject_items(self, thread_id: str, items):
        assert thread_id == "derived-import"
        self.items = items

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        assert thread_id == "derived-import"
        return {
            "id": thread_id,
            "turns": [{"items": self.items if self.preserve_injection else []}],
        }


def test_import_apply_rereads_and_verifies_injected_provenance(
    tmp_path: Path, app_paths, capabilities
) -> None:
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    record = ConversationRecord(
        record_id="record",
        source_type="test-export",
        source_account="old-account",
        source_thread_id="source-thread",
        title="Imported task",
        messages=(ImportMessage(source_id="m1", role="user", text="hello"),),
    )
    plan = ImportPlanner(app_paths).plan(
        source=source,
        records=(record,),
        existing=(),
        capabilities=capabilities,
        confirmed_cwd="/confirmed/project",
    )
    with AuditStore(app_paths) as audit:
        created = LogicalImportExecutor(
            client=_ImportClient(),  # type: ignore[arg-type]
            capabilities=capabilities,
            paths=app_paths,
            audit=audit,
        ).apply(plan, source=source, records=(record,))
    assert created == {"record": "derived-import"}

    failed_plan = ImportPlanner(app_paths).plan(
        source=source,
        records=(record,),
        existing=(),
        capabilities=capabilities,
        confirmed_cwd="/confirmed/project",
    )
    with (
        AuditStore(app_paths) as audit,
        pytest.raises(CsmImportError, match="ordered-message verification"),
    ):
        LogicalImportExecutor(
            client=_ImportClient(preserve_injection=False),  # type: ignore[arg-type]
            capabilities=capabilities,
            paths=app_paths,
            audit=audit,
        ).apply(failed_plan, source=source, records=(record,))
