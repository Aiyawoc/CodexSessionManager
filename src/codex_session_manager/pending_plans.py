"""Lifecycle state for user-reviewed plans waiting for explicit execution."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from codex_session_manager.config import AppPaths, private_atomic_write
from codex_session_manager.hashing import canonical_json_bytes, utc_now


class PendingPlanStatus(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    APPLIED = "applied"


class PendingTrimPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    plan_path: str = Field(min_length=1)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_thread_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
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
        self.root = paths.pending_trim_plans_dir
        self.paths.ensure()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, plan_id: str) -> Path:
        return self.root / f"{plan_id}.json"

    def save(self, entry: PendingTrimPlan) -> Path:
        path = self.path_for(entry.plan_id)
        private_atomic_write(path, canonical_json_bytes(entry))
        return path

    def load(self, path: Path) -> PendingTrimPlan:
        root = self.root.resolve(strict=True)
        if path.is_symlink() or path.resolve(strict=True).parent != root:
            raise ValueError("pending trim plan escaped its private directory")
        entry = PendingTrimPlan.model_validate_json(path.read_bytes())
        if path.resolve(strict=True) != self.path_for(entry.plan_id).resolve(strict=False):
            raise ValueError("pending trim plan path mismatch")
        return entry

    def transition(
        self, entry: PendingTrimPlan, status: PendingPlanStatus, *, reason: str | None = None
    ) -> PendingTrimPlan:
        allowed = {
            PendingPlanStatus.WAITING: {
                PendingPlanStatus.WAITING,
                PendingPlanStatus.READY,
                PendingPlanStatus.INVALIDATED,
                PendingPlanStatus.EXPIRED,
                PendingPlanStatus.CANCELLED,
            },
            PendingPlanStatus.READY: {
                PendingPlanStatus.READY,
                PendingPlanStatus.WAITING,
                PendingPlanStatus.INVALIDATED,
                PendingPlanStatus.EXPIRED,
                PendingPlanStatus.CANCELLED,
                PendingPlanStatus.APPLIED,
            },
            PendingPlanStatus.INVALIDATED: {PendingPlanStatus.INVALIDATED},
            PendingPlanStatus.EXPIRED: {PendingPlanStatus.EXPIRED},
            PendingPlanStatus.CANCELLED: {PendingPlanStatus.CANCELLED},
            PendingPlanStatus.APPLIED: {PendingPlanStatus.APPLIED},
        }
        if status not in allowed[entry.status]:
            raise ValueError(
                f"illegal pending plan transition: {entry.status.value} -> {status.value}"
            )
        now = utc_now()
        updated = entry.model_copy(
            update={
                "status": status,
                "last_checked_at": now,
                "invalid_reason": reason,
                "applied_at": now if status is PendingPlanStatus.APPLIED else entry.applied_at,
                "cancelled_at": (
                    now if status is PendingPlanStatus.CANCELLED else entry.cancelled_at
                ),
            }
        )
        self.save(updated)
        return updated
