from __future__ import annotations

from datetime import UTC, datetime

from codex_session_manager.inventory import (
    InventoryFilter,
    attach_descendant_closures,
    matches_filter,
    model_visible_messages,
    normalize_thread,
)
from codex_session_manager.models import ItemKind, ThreadSnapshot, ThreadStatus


def test_normalize_protects_current_request_unknown_and_active_items() -> None:
    raw = {
        "id": "t1",
        "status": {"type": "active"},
        "ephemeral": True,
        "turns": [
            {
                "id": "turn-1",
                "status": "inProgress",
                "items": [
                    {"id": "u1", "type": "userMessage", "role": "user", "text": "fix"},
                    {"id": "x1", "type": "futureThing", "payload": "opaque"},
                    {"id": "v1", "type": "verificationResult", "text": "tests passed"},
                ],
            }
        ],
    }
    snapshot = normalize_thread(raw, content_complete=True)
    assert snapshot.status is ThreadStatus.ACTIVE
    assert snapshot.ephemeral is True
    assert snapshot.content_complete is True
    user, unknown, verification = snapshot.turns[0].items
    assert user.kind is ItemKind.USER_MESSAGE
    assert user.hard_protected
    assert "current user request" in user.protected_reasons
    assert "turn is still in progress" in user.protected_reasons
    assert unknown.kind is ItemKind.UNKNOWN
    assert unknown.hard_protected
    assert verification.kind is ItemKind.VERIFICATION
    assert verification.hard_protected
    assert snapshot.unknown_item_count == 1


def test_normalize_infers_roles_from_codex_message_item_types() -> None:
    raw = {
        "id": "messages",
        "turns": [
            {
                "id": "turn-1",
                "status": "completed",
                "items": [
                    {"id": "u1", "type": "userMessage", "text": "question"},
                    {"id": "a1", "type": "agentMessage", "text": "answer"},
                ],
            }
        ],
    }

    snapshot = normalize_thread(raw, content_complete=True)
    user, assistant = snapshot.turns[0].items

    assert user.kind is ItemKind.USER_MESSAGE
    assert user.role == "user"
    assert user.hard_protected
    assert assistant.kind is ItemKind.ASSISTANT_MESSAGE
    assert assistant.role == "assistant"
    assert not assistant.hard_protected
    assert model_visible_messages(raw) == (("user", "question"), ("assistant", "answer"))


def test_normalize_tolerates_turn_without_items() -> None:
    snapshot = normalize_thread(
        {"id": "partial", "turns": [{"id": "turn-without-items", "status": "completed"}]},
        content_complete=True,
    )

    assert snapshot.turns[0].items == ()
    assert snapshot.content_complete is False


def test_normalize_marks_incomplete_thread_and_item_shapes() -> None:
    missing_turns = normalize_thread({"id": "missing-turns"}, content_complete=True)
    invalid_item = normalize_thread(
        {"id": "invalid-item", "turns": [{"id": "turn", "items": ["opaque"]}]},
        content_complete=True,
    )

    assert missing_turns.content_complete is False
    assert invalid_item.content_complete is False


def test_descendant_closure_is_transitive_and_orphan_is_incomplete() -> None:
    root = ThreadSnapshot(id="root")
    child = ThreadSnapshot(id="child", parent_id="root")
    grandchild = ThreadSnapshot(id="grand", forked_from_id="child")
    orphan = ThreadSnapshot(id="orphan", parent_id="missing")
    result = {
        item.id: item for item in attach_descendant_closures((root, child, grandchild, orphan))
    }
    assert result["root"].spawned_descendant_ids == ("child", "grand")
    assert result["child"].spawned_descendant_ids == ("grand",)
    assert result["orphan"].mapping_complete is False
    child_filter = InventoryFilter(parent_id="root")
    assert matches_filter(result["child"], child_filter)
    assert not matches_filter(result["grand"], child_filter)


def test_descendant_closure_uses_both_parent_edges_and_rejects_cycles() -> None:
    root = ThreadSnapshot(id="root")
    other = ThreadSnapshot(id="other")
    dual = ThreadSnapshot(id="dual", parent_id="other", forked_from_id="root")
    result = {item.id: item for item in attach_descendant_closures((root, other, dual))}
    assert result["root"].spawned_descendant_ids == ("dual",)
    assert result["other"].spawned_descendant_ids == ("dual",)

    cycle_a = ThreadSnapshot(id="a", parent_id="b")
    cycle_b = ThreadSnapshot(id="b", parent_id="a")
    cycle = {item.id: item for item in attach_descendant_closures((cycle_a, cycle_b))}
    assert cycle["a"].mapping_complete is False
    assert cycle["b"].mapping_complete is False


def test_opaque_payload_changes_item_and_trim_fingerprints() -> None:
    def snapshot(arguments: str) -> ThreadSnapshot:
        return normalize_thread(
            {
                "id": "thread",
                "turns": [
                    {
                        "id": "turn",
                        "items": [
                            {
                                "id": "call",
                                "type": "toolCall",
                                "callId": "c1",
                                "arguments": arguments,
                            },
                            {
                                "id": "result",
                                "type": "toolResult",
                                "callId": "c1",
                                "output": "ok",
                            },
                        ],
                    }
                ],
            },
            content_complete=True,
        )

    first = snapshot('{"path":"one"}')
    second = snapshot('{"path":"two"}')
    assert '"path":"one"' in first.turns[0].items[0].text
    assert first.turns[0].items[0].token_estimate > 0
    assert first.turns[0].items[1].text == "ok"
    assert first.turns[0].items[1].token_estimate > 0
    assert (
        first.turns[0].items[0].content_fingerprint != second.turns[0].items[0].content_fingerprint
    )
    assert first.trim_fingerprint != second.trim_fingerprint

    unpaired = normalize_thread(
        {"id": "u", "turns": [{"id": "t", "items": [{"type": "toolResult"}]}]},
        content_complete=True,
    )
    assert unpaired.turns[0].items[0].hard_protected


def test_inventory_filter_combines_project_remote_time_and_state(snapshot_factory) -> None:
    snapshot = snapshot_factory("match", archived=True, pinned=True)
    snapshot = snapshot.model_copy(
        update={
            "git_remote": "git@example/repo.git",
            "source_kind": "appServer",
            "size_bytes": 4096,
            "preview": "important migration",
        }
    )
    criteria = InventoryFilter(
        cwd="/tmp/project",
        git_remote="git@example/repo.git",
        source_kinds=("appServer",),
        archived=True,
        pinned=True,
        statuses=(ThreadStatus.IDLE,),
        updated_before=datetime(2026, 1, 1, tzinfo=UTC),
        updated_after=datetime(2024, 1, 1, tzinfo=UTC),
        minimum_size=1024,
        maximum_size=8192,
        search="migration",
    )
    assert matches_filter(snapshot, criteria)
    assert not matches_filter(snapshot, criteria.model_copy(update={"search": "missing"}))


class _InventoryClient:
    def __init__(self) -> None:
        self.reads: list[tuple[str, bool]] = []

    def list_threads(self, *, archived: bool = False):
        if archived:
            yield {"id": "archived", "archived": True, "parentThreadId": "active"}
        else:
            yield {"id": "active", "archived": False}

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        self.reads.append((thread_id, include_turns))
        return {
            "id": thread_id,
            "status": {"type": "idle"},
            "turns": [{"id": f"{thread_id}-turn", "status": "completed", "items": []}],
        }


def test_inventory_service_deep_read_preserves_archive_graph() -> None:
    from codex_session_manager.inventory import InventoryService

    client = _InventoryClient()
    snapshots = InventoryService(client).list(include_turns=True)  # type: ignore[arg-type]
    by_id = {item.id: item for item in snapshots}
    assert by_id["archived"].archived is True
    assert by_id["active"].spawned_descendant_ids == ("archived",)
    assert all(item.content_complete for item in snapshots)
    assert client.reads == [("active", True), ("archived", True)]
