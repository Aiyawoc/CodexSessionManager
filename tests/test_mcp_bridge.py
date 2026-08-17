from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from codex_session_manager.mcp_bridge import (
    open_cleanup_review,
    open_review_demo,
    prepare_cleanup_review,
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
