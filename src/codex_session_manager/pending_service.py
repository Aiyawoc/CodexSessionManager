"""Safety-gated operations for plans waiting for user continuation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from codex_session_manager.hashing import utc_now
from codex_session_manager.models import CapabilityMatrix, ThreadStatus, TrimPlan
from codex_session_manager.pending_plans import (
    PendingPlanStatus,
    PendingTrimPlan,
    PendingTrimPlanStore,
)


class PendingCheckResult(StrEnum):
    READY = "ready"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    WAITING = "waiting"


class PendingPlanService:
    """Keep delayed execution behind the same checks as immediate execution."""

    def __init__(self, store: PendingTrimPlanStore) -> None:
        self.store = store

    def check(
        self,
        pending: PendingTrimPlan,
        *,
        plan: TrimPlan,
        capabilities: CapabilityMatrix,
        current_thread_fingerprint: str,
        thread_status: ThreadStatus,
        now: datetime | None = None,
    ) -> PendingCheckResult:
        current = (now or utc_now()).astimezone(UTC)
        if pending.expires_at is not None and current >= pending.expires_at:
            self.store.transition(pending, PendingPlanStatus.EXPIRED, reason="plan expired")
            return PendingCheckResult.EXPIRED
        if plan.plan_sha256 != pending.plan_sha256:
            self.store.transition(pending, PendingPlanStatus.INVALIDATED, reason="plan changed")
            return PendingCheckResult.INVALIDATED
        if plan.source_thread_fingerprint != current_thread_fingerprint:
            self.store.transition(
                pending,
                PendingPlanStatus.INVALIDATED,
                reason="source fingerprint changed",
            )
            return PendingCheckResult.INVALIDATED
        if plan.capability_fingerprint != capabilities.fingerprint:
            self.store.transition(
                pending,
                PendingPlanStatus.INVALIDATED,
                reason="capability fingerprint changed",
            )
            return PendingCheckResult.INVALIDATED
        if thread_status not in {ThreadStatus.IDLE, ThreadStatus.NOT_LOADED}:
            self.store.transition(pending, PendingPlanStatus.WAITING, reason="thread is active")
            return PendingCheckResult.WAITING
        self.store.transition(pending, PendingPlanStatus.READY)
        return PendingCheckResult.READY

    def cancel(self, pending: PendingTrimPlan) -> PendingTrimPlan:
        return self.store.transition(pending, PendingPlanStatus.CANCELLED)

    def applied(self, pending: PendingTrimPlan) -> PendingTrimPlan:
        return self.store.transition(pending, PendingPlanStatus.APPLIED)
