from __future__ import annotations

import pytest

from codex_session_manager.models import TrimAction
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewSource,
    SuggestedAction,
    SuggestionBundle,
    SuggestionTarget,
)
from codex_session_manager.suggestions import ExternalSuggestionBundleProvider
from codex_session_manager.trim import LocalTrimSuggester


def test_external_context_suggestion_rebuilds_local_trim_plan(
    capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("thread-external")
    turn = snapshot.turns[0]
    base = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=turn.id,
                source_fingerprint=turn.content_fingerprint,
                suggested_action=SuggestedAction.SUMMARY,
                suggested_text="由 LLM 提议、由用户最终确认的摘要",
                reason="较早的长内容可以整体摘要",
                confidence=0.88,
            ),
        ),
    )

    result = ExternalSuggestionBundleProvider().apply(
        snapshot=snapshot,
        base_plan=base,
        bundle=bundle,
    )

    selection = next(item for item in result.plan.selections if item.target_id == turn.id)
    assert selection.action is TrimAction.SUMMARY
    assert selection.summary == "由 LLM 提议、由用户最终确认的摘要"
    assert selection.suggested
    assert result.applied_target_ids == (turn.id,)
    assert result.ignored_protected_target_ids == ()
    assert result.plan.source_thread_fingerprint == snapshot.trim_fingerprint


def test_external_context_suggestion_cannot_override_hard_protection(
    capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("thread-protected")
    original_turn = snapshot.turns[0]
    protected_item = original_turn.items[0].model_copy(
        update={
            "hard_protected": True,
            "protected_reasons": ("current user request",),
        }
    )
    turn = original_turn.model_copy(update={"items": (protected_item,)})
    snapshot = snapshot.model_copy(update={"turns": (turn,)})
    base = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=turn.id,
                source_fingerprint=turn.content_fingerprint,
                suggested_action=SuggestedAction.EXCLUDE,
                reason="外部模型错误地要求删除受保护内容",
                confidence=0.99,
            ),
        ),
    )

    result = ExternalSuggestionBundleProvider().apply(
        snapshot=snapshot,
        base_plan=base,
        bundle=bundle,
    )

    selection = next(item for item in result.plan.selections if item.target_id == turn.id)
    assert selection.action is TrimAction.PROTECT
    assert result.applied_target_ids == ()
    assert result.ignored_protected_target_ids == (turn.id,)


def test_external_context_suggestion_rejects_stale_fingerprint(
    capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("thread-stale")
    turn = snapshot.turns[0]
    base = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=turn.id,
                source_fingerprint="stale-fingerprint",
                suggested_action=SuggestedAction.KEEP,
                reason="过期建议",
                confidence=0.5,
            ),
        ),
    )

    with pytest.raises(ValueError, match="fingerprint changed"):
        ExternalSuggestionBundleProvider().apply(
            snapshot=snapshot,
            base_plan=base,
            bundle=bundle,
        )
