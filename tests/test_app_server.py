from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

import codex_session_manager.app_server as app_server
from codex_session_manager.app_server import (
    ALL_SOURCE_KINDS,
    AppServerError,
    ProtocolError,
    RequestTimeout,
    SubprocessAppServer,
    _definition_has_property,
    _extract_methods,
    _generate_schema,
    connect_and_probe,
    probe_capabilities,
)
from codex_session_manager.models import OperationName


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


def test_schema_generation_returns_every_json_document_and_canonical_hash(
    tmp_path: Path, monkeypatch
) -> None:
    def generate(command, **_kwargs):
        output = Path(command[command.index("--out") + 1])
        output.mkdir(parents=True)
        (output / "ClientRequest.json").write_text(
            json.dumps(
                {
                    "definitions": {
                        "ClientRequestMethod": {
                            "title": "ClientRequestMethod",
                            "enum": ["initialize"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (output / "v2/Extra.json").parent.mkdir()
        (output / "v2/Extra.json").write_text('{"title":"Extra"}', encoding="utf-8")

    monkeypatch.setattr(app_server.subprocess, "run", generate)
    documents, methods, digest = _generate_schema(
        "fake-codex", tmp_path / "schema", experimental=False
    )

    assert set(documents) == {"ClientRequest.json", "v2/Extra.json"}
    assert methods == {"initialize"}
    assert len(digest) == 64


def test_probe_generation_failure_returns_five_unavailable_contracts(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise ProtocolError("schema generation failed")

    monkeypatch.setattr(app_server, "_generate_schema", fail)
    monkeypatch.setattr(app_server, "_codex_version", lambda _binary: "test")

    capabilities = probe_capabilities(executable="fake-codex")

    assert capabilities.probe_error == "schema generation failed"
    assert set(capability.operation for capability in capabilities.operation_capabilities) == set(
        OperationName
    )
    assert all(not capability.available for capability in capabilities.operation_capabilities)


def test_request_deadline_is_not_extended_by_notifications() -> None:
    client = SubprocessAppServer(executable="unused")
    for _index in range(100):
        client._messages.put({"method": "notice", "params": {}})
    started = time.monotonic()
    with pytest.raises(RequestTimeout):
        client._wait_for_response(1, 0.05, "thread/read")
    assert time.monotonic() - started < 0.2


def test_timeout_marks_only_write_methods_as_possibly_committed() -> None:
    write_timeout = RequestTimeout("thread/archive", 1.0)
    read_timeout = RequestTimeout("thread/read", 1.0)

    assert write_timeout.may_have_committed
    assert "query actual state" in str(write_timeout)
    assert not read_timeout.may_have_committed


def test_app_server_start_failure_is_typed_and_leaves_no_process(tmp_path) -> None:
    client = SubprocessAppServer(executable=str(tmp_path / "missing-codex"))

    with pytest.raises(AppServerError, match="unable to start Codex App Server"):
        client.start()
    assert client.pid is None


def test_app_server_initialize_failure_closes_started_process(monkeypatch) -> None:
    class StartedProcess:
        pid = 123
        stdin = None
        stdout = None
        stderr = None

        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

    process = StartedProcess()
    monkeypatch.setattr(
        "codex_session_manager.app_server.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    client = SubprocessAppServer(executable="fake-codex")

    def reject_initialize(*_args, **_kwargs):
        raise ProtocolError("initialize failed")

    monkeypatch.setattr(client, "request", reject_initialize)

    with pytest.raises(ProtocolError, match="initialize failed"):
        client.start()

    assert process.terminated
    assert client.pid is None


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
def test_local_codex_schema_probe_reports_operation_contracts() -> None:
    if shutil.which("codex") is None:
        pytest.skip("Codex CLI is unavailable")
    capabilities = probe_capabilities()
    repeated = probe_capabilities()
    assert capabilities.schema_complete
    assert capabilities.codex_binary_sha256
    assert capabilities.schema_sha256
    assert repeated.schema_sha256 == capabilities.schema_sha256
    assert capabilities.supports("thread/list")
    # Codex 0.142.1 has no lastTurnId field; CSM adapts through a derived-only
    # rollback and never sends an undocumented parameter.
    assert isinstance(capabilities.fork_supports_last_turn_id, bool)
    assert capabilities.operation(OperationName.INVENTORY_COMMON).available
    assert capabilities.operation(OperationName.HISTORY_LEGACY).available
    assert capabilities.operation(OperationName.ARCHIVE).available
    assert capabilities.operation(OperationName.UNARCHIVE).available


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
