from __future__ import annotations

import json

import pytest

from codex_session_manager.audit import AuditStore
from codex_session_manager.inventory import normalize_thread
from codex_session_manager.models import (
    ItemKind,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.trim import (
    LocalTrimSuggester,
    TrimError,
    TrimExecutor,
    build_projection,
    prefix_fork_turn,
    validate_selections,
)


def _review_snapshot() -> ThreadSnapshot:
    return normalize_thread(
        {
            "id": "source",
            "title": "Review",
            "status": {"type": "idle"},
            "turns": [
                {
                    "id": "t1",
                    "status": "completed",
                    "items": [
                        {"id": "i1", "type": "agentMessage", "role": "assistant", "text": "ok"}
                    ],
                },
                {
                    "id": "t2",
                    "status": "completed",
                    "items": [
                        {
                            "id": "call",
                            "type": "toolCall",
                            "text": "run",
                            "callId": "c1",
                        },
                        {
                            "id": "result",
                            "type": "toolResult",
                            "text": "large result " * 500,
                            "callId": "c1",
                        },
                    ],
                },
                {
                    "id": "t3",
                    "status": "completed",
                    "items": [
                        {
                            "id": "current",
                            "type": "userMessage",
                            "role": "user",
                            "text": "current request",
                        }
                    ],
                },
            ],
        },
        content_complete=True,
    )


def test_local_suggestions_protect_current_request_and_summarize_tool_chain(
    capabilities,
) -> None:
    snapshot = _review_snapshot()
    plan = LocalTrimSuggester(keep_recent_turns=1, long_turn_tokens=20).suggest(
        snapshot, capabilities=capabilities
    )
    actions = {selection.target_id: selection.action for selection in plan.selections}
    assert actions["t1"] is TrimAction.EXCLUDE
    assert actions["t2"] is TrimAction.SUMMARY
    assert actions["t3"] is TrimAction.PROTECT
    plan.verify()


def test_atomic_tool_items_cannot_receive_conflicting_actions() -> None:
    snapshot = _review_snapshot()
    selections = (
        TrimSelection(
            target_id="call",
            target_level="item",
            action=TrimAction.KEEP,
        ),
        TrimSelection(
            target_id="result",
            target_level="item",
            action=TrimAction.EXCLUDE,
        ),
    )
    with pytest.raises(TrimError, match="atomic tool/file group"):
        validate_selections(snapshot, selections)


def test_non_keep_turn_action_cannot_silently_mask_item_override() -> None:
    snapshot = _review_snapshot()
    selections = (
        TrimSelection(
            target_id="t2",
            action=TrimAction.SUMMARY,
            summary="whole turn summary",
        ),
        TrimSelection(
            target_id="call",
            target_level="item",
            action=TrimAction.SUMMARY,
            summary="edited call",
        ),
    )

    with pytest.raises(TrimError, match="non-keep action together with item overrides"):
        validate_selections(snapshot, selections)


def test_projection_omits_excluded_content_and_seals_manifest(capabilities) -> None:
    snapshot = _review_snapshot()
    selections = (
        TrimSelection(target_id="t1", action=TrimAction.EXCLUDE),
        TrimSelection(
            target_id="t2",
            action=TrimAction.SUMMARY,
            summary="tool operation completed; raw output removed",
        ),
        TrimSelection(target_id="t3", action=TrimAction.PROTECT),
    )
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=selections,
        estimated_tokens_after=25,
    )
    projection = build_projection(snapshot, plan)
    projection.verify()
    visible = "\n".join(entry.text for entry in projection.entries)
    assert "large result" not in visible
    assert "tool operation completed" in visible
    assert "ok" not in visible
    manifest = json.loads(projection.manifest_text)
    assert manifest["trim_plan_sha256"] == plan.plan_sha256
    assert "i1" in manifest["excluded_ids"]


def test_prefix_detection_rejects_non_contiguous_retention(capabilities) -> None:
    snapshot = _review_snapshot()
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(target_id="t1", action=TrimAction.KEEP),
            TrimSelection(target_id="t2", action=TrimAction.EXCLUDE),
            TrimSelection(target_id="t3", action=TrimAction.PROTECT),
        ),
        estimated_tokens_after=10,
    )
    assert prefix_fork_turn(snapshot, plan) is None


class _TrimClient:
    pid = 123

    def __init__(self) -> None:
        self.rollbacks: list[tuple[str, int]] = []

    def fork_thread(self, thread_id: str, *, last_turn_id: str | None = None):
        assert thread_id == "source"
        assert last_turn_id is None
        return {"id": "derived"}

    def rollback_thread(self, thread_id: str, *, num_turns: int):
        self.rollbacks.append((thread_id, num_turns))
        return {"thread": {"id": thread_id}}


class _NoWriteTrimClient(_TrimClient):
    def fork_thread(self, thread_id: str, *, last_turn_id: str | None = None):
        raise AssertionError("invalid plan must be rejected before App Server writes")


class _TrimInventory:
    def __init__(self, source: ThreadSnapshot, derived: ThreadSnapshot) -> None:
        self.source = source
        self.derived = derived
        self.source_reads = 0

    def read(self, thread_id: str, *, include_turns: bool = True) -> ThreadSnapshot:
        assert include_turns
        if thread_id == "derived":
            return self.derived
        self.source_reads += 1
        return self.source


class _ProjectionClient:
    def __init__(self, *, preserve_injection: bool = True) -> None:
        self.preserve_injection = preserve_injection
        self.items: list[dict[str, object]] = []

    def start_thread(self, *, cwd: str | None = None, name: str | None = None):
        assert name == "Review · 精简"
        return {"id": "projection-derived"}

    def inject_items(self, thread_id: str, items):
        assert thread_id == "projection-derived"
        self.items = items

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        assert thread_id == "projection-derived"
        return {
            "id": thread_id,
            "turns": [
                {
                    "id": "injected",
                    "items": self.items if self.preserve_injection else [],
                }
            ],
        }


class _ProjectionInventory:
    def __init__(self, source: ThreadSnapshot) -> None:
        self.source = source

    def read(self, thread_id: str, *, include_turns: bool = True) -> ThreadSnapshot:
        assert thread_id == self.source.id
        assert include_turns
        return self.source


def _non_prefix_plan(source: ThreadSnapshot, capabilities) -> TrimPlan:
    return TrimPlan.create(
        source_thread=source,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(target_id="t1", action=TrimAction.EXCLUDE),
            TrimSelection(target_id="t2", action=TrimAction.SUMMARY, summary="tool summary"),
            TrimSelection(target_id="t3", action=TrimAction.PROTECT),
        ),
        estimated_tokens_after=10,
    )


def test_prefix_apply_adapts_to_fork_then_rollback_without_touching_source(
    app_paths, capabilities, snapshot_factory
) -> None:
    turns = tuple(
        TurnSnapshot(
            id=f"t{index}",
            status="completed",
            items=(
                ThreadItemSnapshot(
                    id=f"i{index}",
                    turn_id=f"t{index}",
                    kind=ItemKind.ASSISTANT_MESSAGE,
                    raw_type="agentMessage",
                    role="assistant",
                    text=f"message {index}",
                    token_estimate=3,
                ),
            ),
        )
        for index in range(1, 4)
    )
    source = snapshot_factory("source", turns=turns, status=ThreadStatus.IDLE)
    derived = snapshot_factory("derived", turns=(turns[0],), status=ThreadStatus.IDLE)
    plan = TrimPlan.create(
        source_thread=source,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(target_id="t1", action=TrimAction.KEEP),
            TrimSelection(target_id="t2", action=TrimAction.EXCLUDE),
            TrimSelection(target_id="t3", action=TrimAction.EXCLUDE),
        ),
        estimated_tokens_after=3,
    )
    client = _TrimClient()
    inventory = _TrimInventory(source, derived)
    with AuditStore(app_paths) as audit:
        target = TrimExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan)
        audit.verify_chain()
    assert target == "derived"
    assert client.rollbacks == [("derived", 2)]
    assert inventory.source_reads == 2


def test_projection_apply_verifies_exact_ordered_injected_message(app_paths, capabilities) -> None:
    source = _review_snapshot()
    client = _ProjectionClient()
    with AuditStore(app_paths) as audit:
        target = TrimExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=_ProjectionInventory(source),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(_non_prefix_plan(source, capabilities))
    assert target == "projection-derived"


def test_projection_apply_rejects_missing_injected_message(app_paths, capabilities) -> None:
    source = _review_snapshot()
    with (
        AuditStore(app_paths) as audit,
        pytest.raises(TrimError, match="ordered-message verification"),
    ):
        TrimExecutor(
            client=_ProjectionClient(preserve_injection=False),  # type: ignore[arg-type]
            inventory=_ProjectionInventory(source),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(_non_prefix_plan(source, capabilities))


def test_trim_apply_requires_explicit_idle_state(app_paths, capabilities, snapshot_factory) -> None:
    source = snapshot_factory("source", status=ThreadStatus.UNKNOWN)
    plan = TrimPlan.create(
        source_thread=source,
        capability_fingerprint=capabilities.fingerprint,
        selections=(TrimSelection(target_id=source.turns[0].id, action=TrimAction.KEEP),),
        estimated_tokens_after=source.token_estimate,
    )
    client = _TrimClient()
    inventory = _TrimInventory(source, source.model_copy(update={"id": "derived"}))
    with AuditStore(app_paths) as audit, pytest.raises(TrimError, match="become idle"):
        TrimExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan)
    assert client.rollbacks == []


def test_trim_apply_revalidates_hard_protection_before_prefix_write(
    app_paths, capabilities, snapshot_factory
) -> None:
    protected_item = ThreadItemSnapshot(
        id="protected",
        turn_id="t2",
        kind=ItemKind.USER_MESSAGE,
        raw_type="userMessage",
        role="user",
        text="current request",
        token_estimate=3,
        hard_protected=True,
        protected_reasons=("current user request",),
    )
    turns = (
        TurnSnapshot(
            id="t1",
            status="completed",
            items=(
                ThreadItemSnapshot(
                    id="i1",
                    turn_id="t1",
                    kind=ItemKind.ASSISTANT_MESSAGE,
                    raw_type="agentMessage",
                    role="assistant",
                    text="retained",
                    token_estimate=2,
                ),
            ),
        ),
        TurnSnapshot(id="t2", status="completed", items=(protected_item,)),
    )
    source = snapshot_factory("source", turns=turns, status=ThreadStatus.IDLE)
    plan = TrimPlan.create(
        source_thread=source,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(target_id="t1", action=TrimAction.KEEP),
            TrimSelection(target_id="t2", action=TrimAction.EXCLUDE),
        ),
        estimated_tokens_after=2,
    )
    inventory = _TrimInventory(source, source.model_copy(update={"id": "derived"}))

    with AuditStore(app_paths) as audit, pytest.raises(TrimError, match="hard-protected"):
        TrimExecutor(
            client=_NoWriteTrimClient(),  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan)
