from __future__ import annotations

import shutil
import time

import pytest

from codex_session_manager.app_server import (
    ALL_SOURCE_KINDS,
    TRUSTED_WRITE_SCHEMAS,
    AppServerError,
    ProtocolError,
    RequestTimeout,
    SubprocessAppServer,
    _definition_has_property,
    _extract_methods,
    connect_and_probe,
    probe_capabilities,
)


def test_schema_walker_ignores_non_string_titles_and_detects_features() -> None:
    schema = {
        "title": {"not": "a string"},
        "definitions": {
            "ThreadForkParams": {"properties": {"lastTurnId": {"type": "string"}}},
            "Method": {
                "title": "Thread/readRequestMethod",
                "enum": ["thread/read"],
            },
        },
    }
    assert _extract_methods(schema) == {"thread/read"}
    assert _definition_has_property(schema, "ThreadForkParams", "lastTurnId")


def test_request_deadline_is_not_extended_by_notifications() -> None:
    client = SubprocessAppServer(executable="unused")
    for _index in range(100):
        client._messages.put({"method": "notice", "params": {}})
    started = time.monotonic()
    with pytest.raises(RequestTimeout):
        client._wait_for_response(1, 0.05, "thread/read")
    assert time.monotonic() - started < 0.2


class _RecordingClient(SubprocessAppServer):
    def __init__(self) -> None:
        super().__init__(executable="unused")
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, method, params=None, *, timeout=None):
        self.requests.append((method, params or {}))
        if method == "thread/list":
            return {"data": [], "nextCursor": None}
        if method == "thread/start":
            return {"thread": {"id": "new"}}
        if method == "thread/name/set":
            return {}
        raise AssertionError(method)


def test_inventory_requests_all_source_kinds_and_start_uses_schema_fields() -> None:
    client = _RecordingClient()
    assert tuple(client.list_threads()) == ()
    params = client.requests[0][1]
    assert params["sourceKinds"] == list(ALL_SOURCE_KINDS)
    assert params["useStateDbOnly"] is True
    client.start_thread(cwd="/tmp/project", name="Imported")
    start_params = next(params for method, params in client.requests if method == "thread/start")
    assert start_params == {"cwd": "/tmp/project"}
    assert "serviceName" not in start_params
    client.rename_thread("new", "Renamed")
    assert client.requests[-1] == (
        "thread/name/set",
        {"threadId": "new", "name": "Renamed"},
    )


def test_thread_read_rejects_mismatched_response_id() -> None:
    class MismatchedReadClient(_RecordingClient):
        def request(self, method, params=None, *, timeout=None):
            return {"thread": {"id": "other"}}

    client = MismatchedReadClient()
    with pytest.raises(ProtocolError, match="different thread id"):
        client.read_thread("expected")


def test_app_server_rejects_mixed_codex_data_roots(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CSM_CODEX_HOME", str(tmp_path / "account-a"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "account-b"))
    with pytest.raises(AppServerError, match="different Codex data roots"):
        SubprocessAppServer(executable="unused").start()


@pytest.mark.integration
def test_local_codex_schema_probe_is_exact_and_fail_closed() -> None:
    if shutil.which("codex") is None:
        pytest.skip("Codex CLI is unavailable")
    capabilities = probe_capabilities()
    repeated = probe_capabilities()
    assert capabilities.schema_complete, capabilities.read_only_reason
    assert capabilities.codex_binary_sha256
    assert capabilities.schema_sha256
    assert repeated.schema_sha256 == capabilities.schema_sha256
    assert capabilities.supports("thread/list")
    # Codex 0.142.1 has no lastTurnId field; CSM adapts through a derived-only
    # rollback and never sends an undocumented parameter.
    assert isinstance(capabilities.fork_supports_last_turn_id, bool)
    if (capabilities.codex_version, capabilities.schema_sha256) in TRUSTED_WRITE_SCHEMAS:
        assert capabilities.write_enabled
    else:
        assert not capabilities.write_enabled
        assert "audited write allowlist" in (capabilities.read_only_reason or "")


@pytest.mark.integration
def test_capability_fingerprint_is_stable_across_connections(tmp_path, monkeypatch) -> None:
    if shutil.which("codex") is None:
        pytest.skip("Codex CLI is unavailable")
    codex_home = tmp_path / "empty-codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CSM_CODEX_HOME", str(codex_home))
    first_client, first = connect_and_probe()
    first_client.close()
    second_client, second = connect_and_probe()
    second_client.close()
    assert first.fingerprint == second.fingerprint
