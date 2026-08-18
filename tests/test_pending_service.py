from __future__ import annotations

from types import SimpleNamespace

from codex_session_manager.pending_service import PendingCheckResult, PendingPlanService


def test_pending_plan_service_transitions_are_safe(tmp_path, app_paths):
    from codex_session_manager.hashing import utc_now
    from codex_session_manager.pending_plans import PendingTrimPlan

    plan = SimpleNamespace(
        plan_id="plan-1",
        plan_sha256="a" * 64,
        source_thread_id="thread-1",
        source_thread_fingerprint="b" * 64,
        capability_fingerprint="capability",
    )
    pending = PendingTrimPlan(
        plan_id=plan.plan_id,
        plan_path=str(tmp_path / "plan.json"),
        plan_sha256=plan.plan_sha256,
        source_thread_id=plan.source_thread_id,
        source_fingerprint=plan.source_thread_fingerprint,
        created_at=utc_now(),
    )
    service = PendingPlanService(
        __import__(
            "codex_session_manager.pending_plans", fromlist=["PendingTrimPlanStore"]
        ).PendingTrimPlanStore(app_paths)
    )
    assert (
        service.check(
            pending,
            plan=plan,
            capabilities=SimpleNamespace(fingerprint="capability"),
            current_thread_fingerprint=plan.source_thread_fingerprint,
            thread_status="idle",
        )
        is PendingCheckResult.READY
    )
    assert service.cancel(pending).status.value == "cancelled"
