from __future__ import annotations

from codex_session_manager.gui.review_state import ReviewState, protected_reasons, target_text
from codex_session_manager.models import TrimAction, TrimSelection


def test_review_state_estimate_and_scope_transitions(snapshot_factory) -> None:
    snapshot = snapshot_factory("review-state")
    turn = snapshot.turns[0]
    item = turn.items[0]
    state = ReviewState.from_selections(
        snapshot,
        (
            TrimSelection(target_id=turn.id, action=TrimAction.EXCLUDE),
            TrimSelection(target_id=item.id, target_level="item", action=TrimAction.KEEP),
        ),
    )

    assert state.estimated_tokens_after() == 0
    state.normalize_selection_scope(item, keep_reason="manual")
    assert state.selections[turn.id].action is TrimAction.KEEP
    assert state.estimated_tokens_after() == item.token_estimate
    state.selections[item.id] = TrimSelection(
        target_id=item.id,
        target_level="item",
        action=TrimAction.SUMMARY,
        summary="short",
    )
    assert state.estimated_tokens_after() == 1
    state.normalize_selection_scope(turn, keep_reason="manual")
    assert item.id not in state.selections


def test_review_state_target_helpers_deduplicate_reasons(snapshot_factory) -> None:
    snapshot = snapshot_factory("review-target")
    turn = snapshot.turns[0]
    item = turn.items[0].model_copy(
        update={"protected_reasons": ("current request", "current request")}
    )
    turn = turn.model_copy(update={"items": (item,)})

    assert protected_reasons(turn) == ("current request",)
    assert target_text(turn) == item.text
    assert target_text(item) == item.text
