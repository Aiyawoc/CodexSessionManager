from __future__ import annotations

from codex_session_manager.pending_plans import (
    PendingPlanStatus,
    PendingTrimPlan,
    PendingTrimPlanStore,
)


def test_pending_trim_plan_lifecycle_can_transition(app_paths) -> None:
    store = PendingTrimPlanStore(app_paths)
    entry = PendingTrimPlan(
        plan_id="plan-1",
        plan_path="/tmp/plan.json",
        plan_sha256="a" * 64,
        source_thread_id="thread-1",
        source_fingerprint="b" * 64,
        created_at=__import__("codex_session_manager.hashing", fromlist=["utc_now"]).utc_now(),
    )
    store.save(entry)
    ready = store.transition(entry, PendingPlanStatus.READY)
    applied = store.transition(ready, PendingPlanStatus.APPLIED)
    assert applied.status is PendingPlanStatus.APPLIED
    assert store.load(store.path_for(entry.plan_id)).status is PendingPlanStatus.APPLIED
