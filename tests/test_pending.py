from __future__ import annotations

from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection
from codex_session_manager.pending import (
    PendingEntryKind,
    PendingEntryState,
    PendingPlanStore,
)
from codex_session_manager.plans import PlanStore
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewRequestQueue,
    ReviewRequestStore,
    ReviewSource,
    codex_account_fingerprint,
)


def test_pending_plan_store_indexes_review_requests_and_trim_plans(
    app_paths, capabilities, snapshot_factory
) -> None:
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.HOOK,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=("thread-1",),
    )
    request_path = ReviewRequestStore(app_paths).save(request)
    ReviewRequestQueue(app_paths).enqueue(request_path)

    snapshot = snapshot_factory("thread-2")
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(
                target_id=snapshot.turns[0].id,
                action=TrimAction.KEEP,
            ),
        ),
        estimated_tokens_after=snapshot.token_estimate,
        trigger="hook",
    )
    PlanStore(app_paths).save(plan)

    entries = PendingPlanStore(app_paths).list_entries()

    assert {entry.kind for entry in entries} == {
        PendingEntryKind.REVIEW_REQUEST,
        PendingEntryKind.TRIM_PLAN,
    }
    assert all(entry.state is PendingEntryState.READY for entry in entries)
    by_kind = {entry.kind: entry for entry in entries}
    assert by_kind[PendingEntryKind.REVIEW_REQUEST].target_id == "thread-1"
    assert by_kind[PendingEntryKind.TRIM_PLAN].target_id == "thread-2"
    assert by_kind[PendingEntryKind.TRIM_PLAN].source == "hook"


def test_pending_plan_store_preserves_invalid_entries_for_review(app_paths) -> None:
    invalid_path = app_paths.plans_dir / "trim-invalid.json"
    app_paths.ensure()
    invalid_path.write_text("not-json", encoding="utf-8")

    entries = PendingPlanStore(app_paths).list_entries()

    assert len(entries) == 1
    assert entries[0].kind is PendingEntryKind.TRIM_PLAN
    assert entries[0].state is PendingEntryState.INVALID
    assert entries[0].path == str(invalid_path)
    assert entries[0].error
    assert invalid_path.is_file()
