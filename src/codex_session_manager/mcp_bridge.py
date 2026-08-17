"""Read-only orchestration helpers intended for a future ChatGPT MCP/App layer."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from codex_session_manager.cleanup import CleanupPlanner, CleanupPolicy
from codex_session_manager.config import AppPaths, get_paths, stable_app_executable
from codex_session_manager.hashing import fingerprint, utc_now
from codex_session_manager.inventory import InventoryFilter
from codex_session_manager.models import ThreadSnapshot
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewRequestQueue,
    ReviewRequestStore,
    ReviewSource,
    SuggestedAction,
    SuggestionBundle,
    SuggestionBundleStore,
    SuggestionTarget,
    codex_account_fingerprint,
)

ReviewLauncher = Callable[[Path], None]


class OpenReviewDemoResult(BaseModel):
    """JSON-friendly result returned by the read-only demo bridge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    operation: ReviewOperation
    request_path: str
    suggestion_bundle_path: str
    pending_request_path: str
    launched: bool
    launch_error: str | None = None

    @classmethod
    def create(
        cls,
        *,
        request: ReviewRequest,
        request_path: Path,
        suggestion_bundle_path: Path,
        pending_request_path: Path,
        launched: bool,
        launch_error: str | None = None,
    ) -> Self:
        return cls(
            request_id=request.request_id,
            operation=request.operation,
            request_path=str(request_path),
            suggestion_bundle_path=str(suggestion_bundle_path),
            pending_request_path=str(pending_request_path),
            launched=launched,
            launch_error=launch_error,
        )


class CleanupReviewResult(BaseModel):
    """Paths and candidate IDs produced by a non-executing cleanup review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    operation: ReviewOperation
    target_ids: tuple[str, ...]
    request_path: str
    suggestion_bundle_path: str
    pending_request_path: str
    launched: bool = False
    launch_error: str | None = None


def _launch_installed_desktop(request_path: Path) -> None:
    executable = stable_app_executable()
    if not executable.is_file():
        raise FileNotFoundError(f"未找到已安装桌面程序：{executable}")
    subprocess.Popen(
        [str(executable), "--request", str(request_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def open_review_demo(
    *,
    paths: AppPaths | None = None,
    launcher: ReviewLauncher | None = None,
) -> OpenReviewDemoResult:
    """Prepare and open a sealed, read-only conversation-cleanup demo request.

    This function is deliberately bounded to CSM-owned request data. It does
    not archive, delete, edit, restore, or otherwise mutate Codex content.
    """

    resolved_paths = paths or get_paths()
    resolved_paths.ensure()
    target_id = f"review-demo-{uuid4()}"
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=target_id,
                source_fingerprint=fingerprint(
                    {
                        "demo_target": target_id,
                        "operation": ReviewOperation.CONVERSATION_CLEANUP.value,
                    }
                ),
                suggested_action=SuggestedAction.ARCHIVE,
                reason="只读桌面链路演示；不代表真实归档建议，也不会执行写入。",
                confidence=0.0,
            ),
        ),
        lifetime=timedelta(minutes=10),
    )
    suggestion_path = SuggestionBundleStore(resolved_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(resolved_paths),
        target_ids=(target_id,),
        suggestion_bundle_path=suggestion_path,
        lifetime=timedelta(minutes=10),
    )
    request_path = ReviewRequestStore(resolved_paths).save(request)
    _queued_request, pending_path = ReviewRequestQueue(resolved_paths).enqueue(request_path)

    launch = launcher or _launch_installed_desktop
    try:
        launch(request_path)
    except OSError as exc:
        return OpenReviewDemoResult.create(
            request=request,
            request_path=request_path,
            suggestion_bundle_path=suggestion_path,
            pending_request_path=pending_path,
            launched=False,
            launch_error=str(exc),
        )
    return OpenReviewDemoResult.create(
        request=request,
        request_path=request_path,
        suggestion_bundle_path=suggestion_path,
        pending_request_path=pending_path,
        launched=True,
    )


def prepare_cleanup_review(
    snapshots: tuple[ThreadSnapshot, ...],
    *,
    paths: AppPaths | None = None,
    older_than_days: int = 90,
    criteria: InventoryFilter | None = None,
    source: ReviewSource = ReviewSource.MCP,
    now: datetime | None = None,
    lifetime: timedelta = timedelta(minutes=30),
) -> CleanupReviewResult | None:
    """Create sealed archive suggestions from deterministic local safety rules.

    No ActionPlan is created and no Codex state is changed. The resulting
    request remains an untrusted suggestion until the GUI rebuilds a final plan
    from current App Server state.
    """

    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")
    resolved_paths = paths or get_paths()
    resolved_paths.ensure()
    effective_now = (now or utc_now()).astimezone(UTC)
    planner = CleanupPlanner(CleanupPolicy(stale_after=timedelta(days=older_than_days)))
    roots = planner.archive_candidates(
        snapshots,
        now=effective_now,
        criteria=criteria,
    )
    if not roots:
        return None

    targets = tuple(
        SuggestionTarget(
            target_id=root.id,
            source_fingerprint=root.management_fingerprint,
            suggested_action=SuggestedAction.ARCHIVE,
            reason=_cleanup_candidate_reason(root, older_than_days),
            confidence=0.85,
        )
        for root in roots
    )
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=source,
        targets=targets,
        lifetime=lifetime,
    )
    suggestion_path = SuggestionBundleStore(resolved_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=source,
        account_root_fingerprint=codex_account_fingerprint(resolved_paths),
        target_ids=tuple(root.id for root in roots),
        suggestion_bundle_path=suggestion_path,
        lifetime=lifetime,
    )
    request_path = ReviewRequestStore(resolved_paths).save(request)
    _queued_request, pending_path = ReviewRequestQueue(resolved_paths).enqueue(request_path)
    return CleanupReviewResult(
        request_id=request.request_id,
        operation=request.operation,
        target_ids=request.target_ids,
        request_path=str(request_path),
        suggestion_bundle_path=str(suggestion_path),
        pending_request_path=str(pending_path),
    )


def open_cleanup_review(
    snapshots: tuple[ThreadSnapshot, ...],
    *,
    paths: AppPaths | None = None,
    older_than_days: int = 90,
    criteria: InventoryFilter | None = None,
    source: ReviewSource = ReviewSource.MCP,
    now: datetime | None = None,
    lifetime: timedelta = timedelta(minutes=30),
    launcher: ReviewLauncher | None = None,
) -> CleanupReviewResult | None:
    """Prepare a safe candidate request and ask the desktop app to review it."""

    prepared = prepare_cleanup_review(
        snapshots,
        paths=paths,
        older_than_days=older_than_days,
        criteria=criteria,
        source=source,
        now=now,
        lifetime=lifetime,
    )
    if prepared is None:
        return None
    launch = launcher or _launch_installed_desktop
    try:
        launch(Path(prepared.request_path))
    except OSError as exc:
        return prepared.model_copy(update={"launched": False, "launch_error": str(exc)})
    return prepared.model_copy(update={"launched": True})


def _cleanup_candidate_reason(root: ThreadSnapshot, older_than_days: int) -> str:
    updated = root.updated_at.isoformat() if root.updated_at is not None else "未知"
    project = root.cwd or root.git_remote or "未指定项目"
    affected = 1 + len(root.spawned_descendant_ids)
    return (
        f"本地安全规则：最后活动 {updated}，已超过 {older_than_days} 天；"
        f"状态 {root.status.value}；项目 {project}；根及已知派生后代共 {affected} 个。"
    )
