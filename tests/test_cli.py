from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import typer
from typer.testing import CliRunner

import codex_session_manager.cli as cli
from codex_session_manager.acceptance import AcceptanceReport
from codex_session_manager.cli import _aware_datetime, _jsonable, app
from codex_session_manager.doctor import _qt_plugin_directory
from codex_session_manager.models import CapabilityMatrix
from codex_session_manager.schema_audit import SchemaAuditReport, build_schema_audit_report
from codex_session_manager.workflows import InventoryResult


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

    mcp = runner.invoke(app, ["mcp", "--help"])
    assert mcp.exit_code == 0
    assert "serve" in mcp.stdout
    assert "stdio" in mcp.stdout

    cleanup = runner.invoke(app, ["cleanup", "--help"])
    assert cleanup.exit_code == 0
    assert "review" in cleanup.stdout
    cleanup_review = runner.invoke(app, ["cleanup", "review", "--help"])
    assert cleanup_review.exit_code == 0
    assert "--older-than-days" in cleanup_review.stdout
    assert "--request" in cleanup_review.stdout

    purge_apply = runner.invoke(app, ["purge", "apply", "--help"])
    assert purge_apply.exit_code == 0
    assert "--confirm" in purge_apply.stdout
    assert "确认删除" in purge_apply.stdout
    assert "--permanent-phrase" not in purge_apply.stdout

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
    assert result.stdout.strip() == "1.1.0"


def test_mcp_serve_builds_secure_http_config(monkeypatch) -> None:
    captured = {}

    def fake_serve(*, config) -> None:
        captured["config"] = config

    monkeypatch.setattr("codex_session_manager.mcp_server.serve_mcp_http", fake_serve)
    monkeypatch.setenv("CSM_MCP_BEARER_TOKEN", "test-only-token")

    result = CliRunner().invoke(
        app,
        [
            "mcp",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--path",
            "/mcp",
            "--allowed-origin",
            "https://chatgpt.com",
            "--allowed-origin",
            "https://chat.openai.com",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.endpoint_path == "/mcp"
    assert config.bearer_token == "test-only-token"
    assert config.allowed_origins == (
        "https://chatgpt.com",
        "https://chat.openai.com",
    )
    assert config.allow_unauthenticated_local is False


def test_mcp_serve_supports_explicit_local_unauthenticated_mode(monkeypatch) -> None:
    captured = {}

    def fake_serve(*, config) -> None:
        captured["config"] = config

    monkeypatch.setattr("codex_session_manager.mcp_server.serve_mcp_http", fake_serve)
    monkeypatch.delenv("CSM_MCP_BEARER_TOKEN", raising=False)

    result = CliRunner().invoke(
        app,
        ["mcp", "serve", "--allow-unauthenticated-local"],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.bearer_token is None
    assert config.allow_unauthenticated_local is True


def test_acceptance_run_fails_when_required_check_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "codex_session_manager.acceptance_runner.run_automated_acceptance",
        lambda *_args, **_kwargs: {
            "delivery_ready": False,
            "production_ready": False,
            "failed_required_checks": ("mcp_security_boundary",),
        },
    )

    result = CliRunner().invoke(
        app,
        ["acceptance", "run", "--output", str(tmp_path / "acceptance.json")],
    )

    assert result.exit_code != 0
    assert "delivery_ready" in result.stdout


def test_inventory_time_filter_requires_explicit_timezone() -> None:
    assert _aware_datetime("2026-08-11T08:00:00+08:00", "--updated-before") == datetime(
        2026, 8, 11, tzinfo=UTC
    )
    with pytest.raises(typer.BadParameter, match="必须包含时区"):
        _aware_datetime("2026-08-11T08:00:00", "--updated-before")


def test_threads_list_builds_csm_age_filter(monkeypatch, capabilities) -> None:
    captured: dict[str, object] = {}

    class FakeWorkflows:
        def list_threads(self, *, criteria=None, include_active=True, include_archived=True):
            captured["criteria"] = criteria
            return InventoryResult(capabilities, ())

    monkeypatch.setattr(cli, "_workflows", lambda: FakeWorkflows())
    result = CliRunner().invoke(app, ["threads", "list", "--older-than-days", "10"])

    assert result.exit_code == 0, result.output
    criteria = captured["criteria"]
    assert criteria.updated_before is not None
    age = datetime.now(UTC) - criteria.updated_before
    assert 9 * 86_400 < age.total_seconds() < 11 * 86_400


def test_threads_list_rejects_ambiguous_age_filters(monkeypatch, capabilities) -> None:
    class NoCallWorkflows:
        def list_threads(self, **_kwargs):
            raise AssertionError("ambiguous filters must be rejected before App Server access")

    monkeypatch.setattr(cli, "_workflows", lambda: NoCallWorkflows())
    result = CliRunner().invoke(
        app,
        [
            "threads",
            "list",
            "--older-than-days",
            "10",
            "--updated-before",
            "2026-08-11T08:00:00+08:00",
        ],
    )

    assert result.exit_code != 0
    assert "不能同时" in result.output


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


def _schema_report(operation_capabilities) -> SchemaAuditReport:
    return build_schema_audit_report(
        CapabilityMatrix(
            codex_version="cli-test",
            codex_binary_sha256="a" * 64,
            initialize_fingerprint="cli-test",
            schema_sha256="b" * 64,
            stable_methods=tuple(
                sorted(
                    {
                        "initialize",
                        "thread/archive",
                        "thread/loaded/list",
                        "thread/read",
                        "thread/turns/list",
                        "thread/list",
                        "thread/unarchive",
                    }
                )
            ),
            experimental_methods=(),
            schema_complete=True,
            operation_capabilities=operation_capabilities,
        )
    )


def test_schema_and_acceptance_cli_write_redacted_non_overwriting_evidence(
    tmp_path, monkeypatch, operation_capabilities
) -> None:
    report = _schema_report(operation_capabilities)
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
