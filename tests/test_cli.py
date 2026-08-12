from __future__ import annotations

from datetime import UTC, datetime

import pytest
import typer
from typer.testing import CliRunner

from codex_session_manager.cli import _aware_datetime, _jsonable, app
from codex_session_manager.doctor import _qt_plugin_directory


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
    ):
        assert command in root.stdout

    codex_import = runner.invoke(app, ["import", "codex", "--help"])
    assert codex_import.exit_code == 0
    assert "plan" in codex_import.stdout
    assert "apply" in codex_import.stdout


def test_cli_version_does_not_contact_app_server() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


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
