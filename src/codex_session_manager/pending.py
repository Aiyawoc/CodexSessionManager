"""Read-only index of review requests and saved trim plans awaiting user action."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict

from codex_session_manager.config import AppPaths
from codex_session_manager.plans import PlanStore
from codex_session_manager.review_requests import ReviewRequestQueue


class PendingEntryKind(StrEnum):
    REVIEW_REQUEST = "review_request"
    TRIM_PLAN = "trim_plan"


class PendingEntryState(StrEnum):
    READY = "ready"
    INVALID = "invalid"


class PendingPlanEntry(BaseModel):
    """Display-safe metadata for one persisted item; never grants write authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str
    kind: PendingEntryKind
    state: PendingEntryState
    path: str
    created_at: AwareDatetime | None = None
    operation: str | None = None
    target_id: str | None = None
    source: str | None = None
    summary: str
    error: str | None = None


class PendingPlanStore:
    """Build a bounded, read-only view over CSM-owned pending artifacts."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.review_queue = ReviewRequestQueue(paths)
        self.plans = PlanStore(paths)

    def list_entries(self) -> tuple[PendingPlanEntry, ...]:
        entries = [*self._review_entries(), *self._trim_plan_entries()]
        return tuple(
            sorted(
                entries,
                key=lambda entry: (
                    entry.created_at is not None,
                    entry.created_at.isoformat() if entry.created_at is not None else "",
                    entry.entry_id,
                ),
                reverse=True,
            )
        )

    def _review_entries(self) -> tuple[PendingPlanEntry, ...]:
        entries: list[PendingPlanEntry] = []
        for path in self.review_queue.entry_paths():
            try:
                queue_entry = self.review_queue.load(path)
                request = self.review_queue.load_request(path)
            except (OSError, ValueError) as exc:
                entries.append(
                    PendingPlanEntry(
                        entry_id=path.stem,
                        kind=PendingEntryKind.REVIEW_REQUEST,
                        state=PendingEntryState.INVALID,
                        path=str(path),
                        summary="待处理审查请求无法通过当前安全校验。",
                        error=str(exc),
                    )
                )
                continue
            target_id = request.target_ids[0] if request.target_ids else None
            entries.append(
                PendingPlanEntry(
                    entry_id=queue_entry.request_id,
                    kind=PendingEntryKind.REVIEW_REQUEST,
                    state=PendingEntryState.READY,
                    path=str(path),
                    created_at=request.created_at,
                    operation=request.operation.value,
                    target_id=target_id,
                    source=request.source.value,
                    summary=(
                        f"{request.operation.value} 审查请求，"
                        f"目标 {len(request.target_ids) + len(request.target_paths)} 个。"
                    ),
                )
            )
        return tuple(entries)

    def _trim_plan_entries(self) -> tuple[PendingPlanEntry, ...]:
        entries: list[PendingPlanEntry] = []
        root = self.paths.plans_dir.resolve(strict=False)
        for path in sorted(self.paths.plans_dir.glob("trim-*.json")):
            try:
                if path.is_symlink() or path.resolve(strict=True).parent != root:
                    raise ValueError("trim plan path escaped the private plans directory")
                plan = self.plans.load_trim(path)
                if path.resolve(strict=True) != self.plans.path_for(plan).resolve(strict=False):
                    raise ValueError("trim plan path does not match its sealed identity")
            except (OSError, ValueError) as exc:
                entries.append(
                    PendingPlanEntry(
                        entry_id=path.stem,
                        kind=PendingEntryKind.TRIM_PLAN,
                        state=PendingEntryState.INVALID,
                        path=str(path),
                        summary="已保存裁剪方案无法通过当前安全校验。",
                        error=str(exc),
                    )
                )
                continue
            entries.append(
                PendingPlanEntry(
                    entry_id=plan.plan_id,
                    kind=PendingEntryKind.TRIM_PLAN,
                    state=PendingEntryState.READY,
                    path=str(path),
                    created_at=plan.created_at,
                    operation="context_trim",
                    target_id=plan.source_thread_id,
                    source=plan.trigger,
                    summary=(
                        f"上下文裁剪方案：{plan.estimated_tokens_before} → "
                        f"{plan.estimated_tokens_after} tokens。"
                    ),
                )
            )
        return tuple(entries)
