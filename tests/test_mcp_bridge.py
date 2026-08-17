from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_session_manager.mcp_bridge import (
    CleanupSuggestionInput,
    ContextSuggestionInput,
    open_cleanup_review,
    open_context_review,
    open_review_demo,
    prepare_cleanup_review,
    prepare_context_review,
)
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequestQueue,
    ReviewRequestStore,
    ReviewSource,
    SuggestedAction,
    SuggestionBundleStore,
)


def test_open_review_demo_prepares_and_queues_read_only_request(app_paths) -> None:
    launched: list[Path] = []

    result = open_review_demo(paths=app_paths, launcher=launched.append)

    assert result.launched
    assert result.launch_error is None
    assert result.operation is ReviewOperation.CONVERSATION_CLEANUP
    assert launched == [Path(result.request_path)]

    request = ReviewRequestStore(app_paths).load(Path(result.request_path))
    bundle = SuggestionBundleStore(app_paths).load(Path(result.suggestion_bundle_path))
    assert request.source is ReviewSource.MCP
    assert bundle.source is ReviewSource.MCP
    assert bundle.targets[0].suggested_action is SuggestedAction.ARCHIVE
    assert bundle.targets[0].confidence == 0.0
    assert ReviewRequestQueue(app_paths).load_request(Path(result.pending_request_path)) == request


def test_open_review_demo_reports_launch_failure_without_dropping_queue(app_paths) -> None:
    def fail_launch(_request_path: Path) -> None:
        raise OSError("desktop unavailable")

    result = open_review_demo(paths=app_paths, launcher=fail_launch)

    assert not result.launched
    assert result.launch_error == "desktop unavailable"
    pending_path = Path(result.pending_request_path)
    assert pending_path.is_file()
    request = ReviewRequestQueue(app_paths).load_request(pending_path)
    assert request.request_id == result.request_id


def test_prepare_cleanup_review_uses_safe_root_candidates_only(app_paths, snapshot_factory) -> None:
    root = snapshot_factory(
        "root",
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    ).model_copy(update={"spawned_descendant_ids": ("child",)})
    child = snapshot_factory(
        "child",
        parent_id="root",
        updated_at=datetime(2025, 1, 2, tzinfo=UTC),
    )
    recent = snapshot_factory(
        "recent",
        updated_at=datetime(2025, 12, 20, tzinfo=UTC),
    )

    result = prepare_cleanup_review(
        (root, child, recent),
        paths=app_paths,
        older_than_days=90,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert result is not None
    assert result.target_ids == ("root",)
    request = ReviewRequestStore(app_paths).load(Path(result.request_path))
    bundle = SuggestionBundleStore(app_paths).load(Path(result.suggestion_bundle_path))
    assert request.target_ids == ("root",)
    assert bundle.targets[0].target_id == "root"
    assert bundle.targets[0].source_fingerprint == root.management_fingerprint
    assert "派生后代共 2 个" in bundle.targets[0].reason
    assert not tuple(app_paths.plans_dir.glob("*.json"))


def test_prepare_cleanup_review_returns_none_when_no_safe_candidates(
    app_paths, snapshot_factory
) -> None:
    pinned = snapshot_factory(
        "pinned",
        pinned=True,
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )

    result = prepare_cleanup_review(
        (pinned,),
        paths=app_paths,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert result is None
    assert not tuple(app_paths.review_requests_dir.glob("*.json"))
    assert not tuple(app_paths.suggestions_dir.glob("*.json"))


def test_open_cleanup_review_preserves_queue_when_desktop_launch_fails(
    app_paths, snapshot_factory
) -> None:
    snapshot = snapshot_factory(
        "old-thread",
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )

    def fail_launch(_request_path: Path) -> None:
        raise OSError("desktop unavailable")

    result = open_cleanup_review(
        (snapshot,),
        paths=app_paths,
        now=datetime(2026, 1, 1, tzinfo=UTC),
        launcher=fail_launch,
    )

    assert result is not None
    assert not result.launched
    assert result.launch_error == "desktop unavailable"
    assert Path(result.pending_request_path).is_file()


def test_prepare_cleanup_review_accepts_only_llm_subset_of_local_safe_pool(
    app_paths, snapshot_factory
) -> None:
    first = snapshot_factory(
        "old-first",
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    second = snapshot_factory(
        "old-second",
        updated_at=datetime(2025, 1, 2, tzinfo=UTC),
    )

    result = prepare_cleanup_review(
        (first, second),
        paths=app_paths,
        now=datetime(2026, 1, 1, tzinfo=UTC),
        llm_suggestions=(
            CleanupSuggestionInput(
                target_id=second.id,
                reason="LLM 初筛后只建议归档第二个对话",
                confidence=0.92,
            ),
        ),
    )

    assert result is not None
    assert result.target_ids == (second.id,)
    bundle = SuggestionBundleStore(app_paths).load(Path(result.suggestion_bundle_path))
    assert bundle.targets[0].source_fingerprint == second.management_fingerprint
    assert bundle.targets[0].reason == "LLM 初筛后只建议归档第二个对话"

    with pytest.raises(ValueError, match="outside the local safe candidate pool"):
        prepare_cleanup_review(
            (first,),
            paths=app_paths,
            now=datetime(2026, 1, 1, tzinfo=UTC),
            llm_suggestions=(
                CleanupSuggestionInput(
                    target_id="not-safe",
                    reason="越权候选",
                    confidence=1.0,
                ),
            ),
        )


def test_prepare_context_review_binds_llm_targets_to_current_fingerprints(
    app_paths, snapshot_factory
) -> None:
    snapshot = snapshot_factory("context-bridge")
    turn = snapshot.turns[0]

    result = prepare_context_review(
        snapshot,
        (
            ContextSuggestionInput(
                target_id=turn.id,
                suggested_action=SuggestedAction.SUMMARY,
                suggested_text="由用户复核的摘要",
                reason="LLM 初筛建议摘要",
                confidence=0.81,
            ),
        ),
        paths=app_paths,
    )

    request = ReviewRequestStore(app_paths).load(Path(result.request_path))
    bundle = SuggestionBundleStore(app_paths).load(Path(result.suggestion_bundle_path))
    assert result.thread_id == snapshot.id
    assert request.target_ids == (snapshot.id,)
    assert bundle.targets[0].target_id == turn.id
    assert bundle.targets[0].source_fingerprint == turn.content_fingerprint
    assert ReviewRequestQueue(app_paths).load_request(Path(result.pending_request_path)) == request


def test_open_context_review_keeps_queue_when_desktop_launch_fails(
    app_paths, snapshot_factory
) -> None:
    snapshot = snapshot_factory("context-launch-fail")
    turn = snapshot.turns[0]

    def fail_launch(_request_path: Path) -> None:
        raise OSError("desktop unavailable")

    result = open_context_review(
        snapshot,
        (
            ContextSuggestionInput(
                target_id=turn.id,
                suggested_action=SuggestedAction.KEEP,
                reason="保留",
                confidence=0.8,
            ),
        ),
        paths=app_paths,
        launcher=fail_launch,
    )

    assert not result.launched
    assert result.launch_error == "desktop unavailable"
    assert Path(result.pending_request_path).is_file()
