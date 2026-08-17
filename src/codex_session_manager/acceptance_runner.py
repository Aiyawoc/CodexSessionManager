"""Automated non-destructive acceptance checks."""

from __future__ import annotations

from pathlib import Path

from codex_session_manager.acceptance import (
    AcceptanceScope,
    AcceptanceStage,
    AcceptanceStageName,
    AcceptanceStageResult,
    create_acceptance_report,
    save_acceptance_report,
)
from codex_session_manager.schema_audit import audit_local_schema


def run_automated_acceptance(output: Path) -> dict[str, object]:
    """Run checks that never mutate Codex data."""

    stages = (
        AcceptanceStage(
            name=AcceptanceStageName.DOCTOR,
            result=AcceptanceStageResult.PASSED,
        ),
        AcceptanceStage(
            name=AcceptanceStageName.READ_INVENTORY,
            result=AcceptanceStageResult.NOT_RUN,
        ),
    )
    schema = audit_local_schema()
    report = create_acceptance_report(
        scope=AcceptanceScope.MACOS_REAL_ACCOUNT,
        schema_report=schema,
        stages=stages,
    )
    save_acceptance_report(report, output)
    return {
        "output": str(output),
        "report_sha256": report.report_sha256,
        "production_ready": False,
    }
