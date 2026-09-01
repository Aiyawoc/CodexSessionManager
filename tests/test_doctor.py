from __future__ import annotations

from typing import Any

from codex_session_manager.app_server import AppServerError
from codex_session_manager.doctor import run_doctor


class _ClosingClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _check(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(check for check in report["checks"] if check["name"] == name)


def test_doctor_reports_capabilities_and_closes_connection(
    app_paths, capabilities, monkeypatch
) -> None:
    client = _ClosingClient()
    monkeypatch.setattr(
        "codex_session_manager.doctor.connect_and_probe",
        lambda **_kwargs: (client, capabilities),
    )

    report = run_doctor(app_paths)

    assert client.closed
    assert report["capabilities"]["fingerprint"] == capabilities.fingerprint
    assert report["capabilities"]["write_enabled"] is True
    assert report["capabilities"]["purge_execution_enabled"] is False
    assert _check(report, "Codex App Server")["ok"] is True
    writes = _check(report, "Codex App Server writes")
    assert writes["ok"] is True
    assert writes["required"] is False
    purge = _check(report, "permanent purge application")
    assert purge["ok"] is False
    assert purge["required"] is False
    assert "CLOSED_WITH_UPSTREAM_BLOCKER" in purge["detail"]


def test_doctor_turns_app_server_start_failure_into_a_failed_check(app_paths, monkeypatch) -> None:
    def fail(**_kwargs):
        raise AppServerError("test App Server startup failure")

    monkeypatch.setattr("codex_session_manager.doctor.connect_and_probe", fail)

    report = run_doctor(app_paths)

    app_server = _check(report, "Codex App Server")
    assert app_server["ok"] is False
    assert app_server["required"] is True
    assert "startup failure" in app_server["detail"]
    assert report["capabilities"] is None
    assert report["ok"] is False


def test_doctor_can_skip_app_server_without_calling_it(app_paths, monkeypatch) -> None:
    def unexpected(**_kwargs):
        raise AssertionError("App Server must not be contacted")

    monkeypatch.setattr("codex_session_manager.doctor.connect_and_probe", unexpected)

    report = run_doctor(app_paths, probe_app_server=False)

    assert not any(check["name"] == "Codex App Server" for check in report["checks"])
    assert report["capabilities"] is None
