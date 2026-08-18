from __future__ import annotations

from codex_session_manager.pending import PendingEntryKind


def test_pending_entry_kind_supports_trim_lifecycle() -> None:
    assert PendingEntryKind.PENDING_TRIM_PLAN.value == "pending_trim_plan"
