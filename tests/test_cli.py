from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import typer
from typer.testing import CliRunner

from codex_session_manager.acceptance import AcceptanceReport
from codex_session_manager.cli import _aware_datetime, _jsonable, app
from codex_session_manager.doctor import _qt_plugin_directory
from codex_session_manager.models import CapabilityMatrix
from codex_session_manager.protocol_profiles import AUDITED_PROTOCOL_PROFILES
from codex_session_manager.schema_audit import SchemaAuditReport, build_schema_audit_report


def test_cli_exposes_planned_command_surface() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["--help"])
    assert root.exit_code == 0
    for command in (
        "threads",
        "cleanup",
        "purge",
        "backup",
        "restore",
        "import",
        "trim",
        "hook",
        "audit",
        "schema",
        "acceptance",
        "gui",
        "mcp",
        "memory",
    ):
        assert command in root.stdout

    codex_import = runner.invoke(app, ["import", "codex", "--help"])
    assert codex_import.exit_code == 0
    assert "plan" in codex_import.stdout
    assert "apply" in codex_import.stdout

    gui = runner.invoke(app, ["gui", "open", "--help"])
    assert gui.exit_code == 0
    assert "--request" in gui.stdout
    assert "--page" in gui.stdout
    assert "--thread" in gui.stdout

    cleanup = runner.invoke(app, ["cleanup", "--help"])
    assert cleanup.exit_code == 0
    assert "review" in cleanup.stdout
    cleanup_review = runner.invoke(app, ["cleanup", "review", "--help"])
    assert cleanup_review.exit_code == 0
    assert "--older-than-days" in cleanup_review.stdout
    assert "--request" in cleanup_review.stdout

    memory = runner.invoke(app, ["memory", "--help"])
    assert memory.exit_code == 0
    for command in (
        "register",
        "unregister",
        "sources",
        "list",
        "show",
        "suggest",
        "review",
        "plan",
        "apply",
        "history",
        "restore",
    ):
        assert command in memory.stdout
    memory_restore = runner.invoke(app, ["memory", "restore", "--help"])
    assert memory_restore.exit_code == 0
    assert "plan" in memory_restore.stdout
    assert "apply" in memory_restore.stdout

    acceptance = runner.invoke(app, ["acceptance", "--help"])
    assert acceptance.exit_code == 0
    assert "run" in acceptance.stdout
    assert "release" in acceptance.stdout


def test_cli_version_does_not_contact_app_server() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "1.0.1"


def test_inventory_time_filter_requires_explicit_timezone() -> None:
    assert _aware_datetime("2026-08-11T08:00:00+08:00", "--updated-before") == datetime(
        2026, 8, 11, tzinfo=UTC
    )
    with pytest.raises(typer.BadParameter, match="必须包含时区"):
        _aware_datetime("2026-08-11T08:00:00", "--updated-before")


def test_cli_jsonable_serializes_raw_dates_in_app_server_payloads() -> None:
    value = {
        "created_at": datetime(2026, 8, 11, 12, 34, 56, tzinfo=UTC),
        "due_date": datetime(2026, 8, 12, tzinfo=UTC).date(),
    }

    assert _jsonable(value) == {
        "created_at": "2026-08-11T12:34:56+00:00",
        "due_date": "2026-08-12",
    }


def test_doctor_resolves_nuitka_qt_plugin_layout(tmp_path) -> None:
    contents = tmp_path / "Example.app" / "Contents"
    bundled_plugins = contents / "MacOS" / "PySide6" / "qt-plugins"
    bundled_plugins.mkdir(parents=True)

    result = _qt_plugin_directory(tmp_path / "reported-but-missing", contents)

    assert result == bundled_plugins


def _trusted_schema_report() -> SchemaAuditReport:
    profile = next(iter(AUDITED_PROTOCOL_PROFILES.values()))
    return build_schema_audit_report(
        CapabilityMatrix(
            codex_version=profile.codex_version,
            codex_binary_sha256="a" * 64,
            initialize_fingerprint="cli-test",
            schema_sha256=profile.schema_sha256,
            stable_methods=tuple(sorted(profile.stable_methods)),
            experimental_methods=tuple(sorted(profile.experimental_methods)),
            schema_complete=True,
        )
    )


def test_schema_and_acceptance_cli_write_redacted_non_overwriting_evidence(
    tmp_path, monkeypatch
) -> None:
    report = _trusted_schema_report()
    monkeypatch.setattr("codex_session_manager.cli.audit_local_schema", lambda: report)
    schema_path = tmp_path / "schema-audit.json"
    runner = CliRunner()

    audited = runner.invoke(app, ["schema", "audit", "--output", str(schema_path)])
    assert audited.exit_code == 0, audited.output
    audited_payload = json.loads(audited.stdout)
    assert audited_payload["output_name"] == schema_path.name
    assert str(tmp_path) not in audited.stdout
    persisted_schema = SchemaAuditReport.model_validate_json(schema_path.read_bytes())
    persisted_schema.verify()

    repeated = runner.invoke(app, ["schema", "audit", "--output", str(schema_path)])
    assert repeated.exit_code != 0
    assert "禁止覆盖" in repeated.output

    raw_thread_id = "private-task-id"
    acceptance_path = tmp_path / "acceptance.json"
    accepted = runner.invoke(
        app,
        [
            "acceptance",
            "report",
            str(acceptance_path),
            "--schema-report",
            str(schema_path),
            "--thread-id",
            raw_thread_id,
            "--stage",
            "doctor=passed",
        ],
    )
    assert accepted.exit_code == 0, accepted.output
    persisted_acceptance = AcceptanceReport.model_validate_json(acceptance_path.read_bytes())
    persisted_acceptance.verify()
    assert raw_thread_id not in acceptance_path.read_text(encoding="utf-8")
    assert persisted_acceptance.production_ready is False
