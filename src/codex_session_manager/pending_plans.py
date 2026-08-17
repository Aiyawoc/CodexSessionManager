"""Lifecycle state for user-reviewed plans waiting for explicit execution."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict

from codex_session_manager.config import AppPaths
from codex_session_manager.hashing import utc_now


class PendingPlanStatus(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    APPLIED = "applied"


class PendingTrimPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    plan_path: str
    plan_sha256: str
    source_thread_id: str
    source_fingerprint: str
    created_at: AwareDatetime
    status: PendingPlanStatus = PendingPlanStatus.WAITING
    expires_at: AwareDatetime | None = None
    last_checked_at: AwareDatetime | None = None
    invalid_reason: str | None = None
    applied_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None


class PendingTrimPlanStore:
    """Atomic JSON-backed lifecycle store for pending trim plans."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.root = paths.data_dir / "pending-trim-plans"
        self.paths.ensure()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, plan_id: str) -> Path:
        return self.root / f"{plan_id}.json"

    def save(self, entry: PendingTrimPlan) -> Path:
        path = self.path_for(entry.plan_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(entry.model_dump_json().encode("utf-8"))
        tmp.replace(path)
        return path

    def load(self, path: Path) -> PendingTrimPlan:
        entry = PendingTrimPlan.model_validate_json(path.read_bytes())
        if path.resolve() != self.path_for(entry.plan_id).resolve():
            raise ValueError("pending trim plan path mismatch")
        return entry

    def transition(
        self, entry: PendingTrimPlan, status: PendingPlanStatus, *, reason: str | None = None
    ) -> PendingTrimPlan:
        updated = entry.model_copy(
            update={
                "status": status,
                "last_checked_at": utc_now(),
                "invalid_reason": reason,
                "applied_at": utc_now()
                if status is PendingPlanStatus.APPLIED
                else entry.applied_at,
                "cancelled_at": utc_now()
                if status is PendingPlanStatus.CANCELLED
                else entry.cancelled_at,
            }
        )
        self.save(updated)
        return updated
