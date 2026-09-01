from codex_session_manager.acceptance import AcceptanceReport


def test_acceptance_report_limitations_retire_permanent_delete() -> None:
    limitations = AcceptanceReport.model_fields["limitations"].default

    assert "no-permanent-delete" not in limitations
    assert {
        "no-restore-or-import",
        "no-real-hook-install",
        "not-production-acceptance",
    } <= set(limitations)
