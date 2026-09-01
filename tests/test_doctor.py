from __future__ import annotations

from typing import Any

from codex_session_manager.app_server import AppServerError
from codex_session_manager.doctor import run_doctor
from codex_session_manager.models import ContractIssue, OperationName


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
    assert {
        capability["operation"] for capability in report["capabilities"]["operation_capabilities"]
    } == {operation.value for operation in OperationName}
    assert "write_enabled" not in report["capabilities"]
    assert report["capabilities"]["purge_execution_enabled"] is False
    assert _check(report, "Codex App Server")["ok"] is True
    assert _check(report, OperationName.ARCHIVE.value)["ok"] is True
    assert _check(report, OperationName.UNARCHIVE.value)["ok"] is True
    assert _check(report, OperationName.HISTORY_PAGINATED.value)["ok"] is True
    assert _check(report, "Codex App Server")["required"] is True
    assert not any(check["name"] == "Codex App Server writes" for check in report["checks"])
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


def test_doctor_keeps_common_inventory_required_when_one_operation_is_unavailable(
    app_paths, capabilities, monkeypatch
) -> None:
    archive = capabilities.operation(OperationName.ARCHIVE).model_copy(
        update={
            "available": False,
            "runtime_contract_fingerprint": None,
            "method_evidence": (),
            "issues": (ContractIssue(code="missing_method", subject="thread/archive"),),
        }
    )
    partial = capabilities.model_copy(
        update={
            "operation_capabilities": tuple(
                archive if item.operation is OperationName.ARCHIVE else item
                for item in capabilities.operation_capabilities
            )
        }
    )
    monkeypatch.setattr(
        "codex_session_manager.doctor.connect_and_probe",
        lambda **_kwargs: (_ClosingClient(), partial),
    )

    report = run_doctor(app_paths)

    assert _check(report, "Codex App Server")["ok"] is True
    assert _check(report, OperationName.ARCHIVE.value) == {
        "name": OperationName.ARCHIVE.value,
        "ok": False,
        "detail": "missing_method: thread/archive",
        "required": False,
    }


def test_doctor_can_skip_app_server_without_calling_it(app_paths, monkeypatch) -> None:
    def unexpected(**_kwargs):
        raise AssertionError("App Server must not be contacted")

    monkeypatch.setattr("codex_session_manager.doctor.connect_and_probe", unexpected)

    report = run_doctor(app_paths, probe_app_server=False)

    assert not any(check["name"] == "Codex App Server" for check in report["checks"])
    assert report["capabilities"] is None
