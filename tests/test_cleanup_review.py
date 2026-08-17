from __future__ import annotations

import pytest

from codex_session_manager.cleanup_review import build_cleanup_action_plan
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewSource,
    SuggestedAction,
    SuggestionBundle,
    SuggestionTarget,
    codex_account_fingerprint,
)


def _review_request(app_paths, snapshots):
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=tuple(
            SuggestionTarget(
                target_id=snapshot.id,
                source_fingerprint=snapshot.management_fingerprint,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="本地安全候选",
                confidence=0.8,
            )
            for snapshot in snapshots
        ),
    )
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=tuple(snapshot.id for snapshot in snapshots),
        suggestion_bundle_path=app_paths.suggestions_dir / f"suggestion-{bundle.bundle_id}.json",
    )
    return request, bundle


def test_cleanup_action_plan_contains_only_final_user_selection(
    app_paths, capabilities, snapshot_factory
) -> None:
    first = snapshot_factory("first")
    second = snapshot_factory("second")
    request, bundle = _review_request(app_paths, (first, second))

    plan = build_cleanup_action_plan(
        request=request,
        bundle=bundle,
        selected_ids=("second",),
        snapshots=(first, second),
        capabilities=capabilities,
    )

    assert tuple(target.root_thread_id for target in plan.targets) == ("second",)
    assert plan.options["manual_selection"] is True
    assert plan.options["automatic_ceiling"] == "archive"


def test_cleanup_action_plan_rejects_stale_suggestion(
    app_paths, capabilities, snapshot_factory
) -> None:
    original = snapshot_factory("thread-1")
    request, bundle = _review_request(app_paths, (original,))
    changed = original.model_copy(update={"title": "changed after suggestion"})

    with pytest.raises(ValueError, match="stale"):
        build_cleanup_action_plan(
            request=request,
            bundle=bundle,
            selected_ids=("thread-1",),
            snapshots=(changed,),
            capabilities=capabilities,
        )


def test_cleanup_action_plan_rejects_target_outside_request(
    app_paths, capabilities, snapshot_factory
) -> None:
    requested = snapshot_factory("requested")
    outside = snapshot_factory("outside")
    request, bundle = _review_request(app_paths, (requested,))

    with pytest.raises(ValueError, match="outside the review request"):
        build_cleanup_action_plan(
            request=request,
            bundle=bundle,
            selected_ids=("outside",),
            snapshots=(requested, outside),
            capabilities=capabilities,
        )
