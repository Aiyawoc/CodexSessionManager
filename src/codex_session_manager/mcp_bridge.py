"""Read-only orchestration helpers intended for a future ChatGPT MCP/App layer."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_session_manager.cleanup import CleanupPlanner, CleanupPolicy
from codex_session_manager.config import AppPaths, get_paths, stable_app_executable
from codex_session_manager.hashing import fingerprint, utc_now
from codex_session_manager.inventory import InventoryFilter
from codex_session_manager.models import ThreadItemSnapshot, ThreadSnapshot, TurnSnapshot
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


class CleanupSuggestionInput(BaseModel):
    """LLM ranking data; identity and fingerprints are rebuilt locally."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ContextSuggestionInput(BaseModel):
    """Untrusted LLM context suggestion before local target binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    suggested_action: SuggestedAction
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_text: str | None = None

    @model_validator(mode="after")
    def validate_context_action(self) -> Self:
        allowed = {
            SuggestedAction.KEEP,
            SuggestedAction.EXCLUDE,
            SuggestedAction.SUMMARY,
            SuggestedAction.PROTECT,
        }
        if self.suggested_action not in allowed:
            raise ValueError("context suggestion action is not allowed")
        if (
            self.suggested_action is SuggestedAction.SUMMARY
            and not (self.suggested_text or "").strip()
        ):
            raise ValueError("context summary suggestion requires suggested_text")
        return self


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


class ContextReviewResult(BaseModel):
    """Sealed context request built from LLM suggestions and current fingerprints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    operation: ReviewOperation
    thread_id: str
    suggestion_target_ids: tuple[str, ...]
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
    llm_suggestions: tuple[CleanupSuggestionInput, ...] | None = None,
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

    roots_by_id = {root.id: root for root in roots}
    if llm_suggestions is None:
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
    else:
        if not llm_suggestions:
            return None
        suggestion_ids = [suggestion.target_id for suggestion in llm_suggestions]
        if len(suggestion_ids) != len(set(suggestion_ids)):
            raise ValueError("LLM cleanup suggestions contain duplicate target ids")
        targets_list: list[SuggestionTarget] = []
        for suggestion in llm_suggestions:
            root = roots_by_id.get(suggestion.target_id)
            if root is None:
                raise ValueError(
                    "LLM cleanup suggestion is outside the local safe candidate pool: "
                    f"{suggestion.target_id}"
                )
            targets_list.append(
                SuggestionTarget(
                    target_id=root.id,
                    source_fingerprint=root.management_fingerprint,
                    suggested_action=SuggestedAction.ARCHIVE,
                    reason=suggestion.reason,
                    confidence=suggestion.confidence,
                )
            )
        targets = tuple(targets_list)
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
        target_ids=tuple(target.target_id for target in targets if target.target_id is not None),
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
    llm_suggestions: tuple[CleanupSuggestionInput, ...] | None = None,
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
        llm_suggestions=llm_suggestions,
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


def prepare_context_review(
    snapshot: ThreadSnapshot,
    suggestions: tuple[ContextSuggestionInput, ...],
    *,
    paths: AppPaths | None = None,
    source: ReviewSource = ReviewSource.MCP,
    lifetime: timedelta = timedelta(minutes=30),
) -> ContextReviewResult:
    """Bind LLM context suggestions to current turn/item fingerprints and queue review."""

    if not snapshot.content_complete or not snapshot.mapping_complete:
        raise ValueError("context review requires complete content and lineage mapping")
    if not suggestions:
        raise ValueError("context review requires at least one suggestion")
    suggestion_ids = [suggestion.target_id for suggestion in suggestions]
    if len(suggestion_ids) != len(set(suggestion_ids)):
        raise ValueError("context suggestions contain duplicate target ids")
    targets_by_id: dict[str, TurnSnapshot | ThreadItemSnapshot] = {}
    for turn in snapshot.turns:
        targets_by_id[turn.id] = turn
        for item in turn.items:
            targets_by_id[item.id] = item
    targets: list[SuggestionTarget] = []
    for suggestion in suggestions:
        target = targets_by_id.get(suggestion.target_id)
        if target is None:
            raise ValueError(
                f"context suggestion is outside the current conversation: {suggestion.target_id}"
            )
        targets.append(
            SuggestionTarget(
                target_id=suggestion.target_id,
                source_fingerprint=target.content_fingerprint,
                suggested_action=suggestion.suggested_action,
                reason=suggestion.reason,
                confidence=suggestion.confidence,
                suggested_text=suggestion.suggested_text,
            )
        )

    resolved_paths = paths or get_paths()
    resolved_paths.ensure()
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=source,
        targets=tuple(targets),
        lifetime=lifetime,
    )
    suggestion_path = SuggestionBundleStore(resolved_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=source,
        account_root_fingerprint=codex_account_fingerprint(resolved_paths),
        target_ids=(snapshot.id,),
        suggestion_bundle_path=suggestion_path,
        lifetime=lifetime,
    )
    request_path = ReviewRequestStore(resolved_paths).save(request)
    _queued_request, pending_path = ReviewRequestQueue(resolved_paths).enqueue(request_path)
    return ContextReviewResult(
        request_id=request.request_id,
        operation=request.operation,
        thread_id=snapshot.id,
        suggestion_target_ids=tuple(suggestion_ids),
        request_path=str(request_path),
        suggestion_bundle_path=str(suggestion_path),
        pending_request_path=str(pending_path),
    )


def open_context_review(
    snapshot: ThreadSnapshot,
    suggestions: tuple[ContextSuggestionInput, ...],
    *,
    paths: AppPaths | None = None,
    source: ReviewSource = ReviewSource.MCP,
    lifetime: timedelta = timedelta(minutes=30),
    launcher: ReviewLauncher | None = None,
) -> ContextReviewResult:
    """Prepare a locally bound context request and open it in the original GUI."""

    prepared = prepare_context_review(
        snapshot,
        suggestions,
        paths=paths,
        source=source,
        lifetime=lifetime,
    )
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
