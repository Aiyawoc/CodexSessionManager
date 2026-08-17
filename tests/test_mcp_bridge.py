from __future__ import annotations

from pathlib import Path

from codex_session_manager.mcp_bridge import open_review_demo
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
