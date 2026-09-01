from __future__ import annotations

from pathlib import Path

import pytest

from codex_session_manager.acceptance_runner import (
    AutomatedAcceptanceReport,
    AutomatedCheckStatus,
    run_automated_acceptance,
)


def test_automated_acceptance_runs_real_isolated_first_delivery_checks(
    tmp_path: Path,
) -> None:
    output = tmp_path / "acceptance.json"

    result = run_automated_acceptance(output)

    markdown = tmp_path / "acceptance.md"
    assert result["delivery_ready"] is True
    assert result["production_ready"] is False
    assert output.is_file()
    assert markdown.is_file()
    report = AutomatedAcceptanceReport.model_validate_json(output.read_bytes())
    report.verify()
    required = [check for check in report.checks if check.required]
    assert required
    assert all(check.status is AutomatedCheckStatus.PASSED for check in required)
    assert {check.name for check in required} == {
        "mcp_security_boundary",
        "memory_round_trip",
        "pending_plan_lifecycle",
        "original_gui_memory_mode",
    }
    assert "首次交付就绪：`true`" in markdown.read_text(encoding="utf-8")
    assert "永久删除" not in markdown.read_text(encoding="utf-8")
    assert report.limitations == (
        "Codex desktop 本机 MCP 的 stdio 启动、工具发现和真实 GUI 行为需要在目标测试机人工验收",
        "HTTP MCP、远程连接器和 Tunnel 不属于本机 stdio 自动门禁；如启用需另行验收",
        "Apple 签名、公证和 Windows 原生运行不由本地自动检查声称完成",
        "production_ready 始终为 false；本报告只判断首次用户交付门槛",
    )

    with pytest.raises(FileExistsError):
        run_automated_acceptance(output)


def test_release_acceptance_requires_age_tools_and_stable_app(tmp_path: Path, monkeypatch) -> None:
    age = tmp_path / "age"
    age_keygen = tmp_path / "age-keygen"
    app = tmp_path / "CodexSessionManager"
    age.write_bytes(b"age")
    age_keygen.write_bytes(b"age-keygen")
    app.write_bytes(b"app")
    monkeypatch.setattr(
        "codex_session_manager.acceptance_runner.bundled_age_path",
        lambda **_kwargs: age,
    )
    monkeypatch.setattr(
        "codex_session_manager.acceptance_runner.bundled_age_keygen_path",
        lambda **_kwargs: age_keygen,
    )
    monkeypatch.setattr(
        "codex_session_manager.acceptance_runner.stable_app_executable",
        lambda: app,
    )

    output = tmp_path / "release.json"
    result = run_automated_acceptance(output, release_mode=True)
    report = AutomatedAcceptanceReport.model_validate_json(output.read_bytes())

    assert result["delivery_ready"] is True
    assert all(check.required for check in report.checks)
    assert all(check.status is AutomatedCheckStatus.PASSED for check in report.checks)
