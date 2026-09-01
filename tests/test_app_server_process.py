from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import OperationName
from codex_session_manager.version import __version__

PROJECT_ROOT = Path(__file__).parents[1]
FAKE_CODEX_SOURCE = r"""
import json
import os
import sys
from pathlib import Path

METHODS = [
    "initialize",
    "thread/list",
    "thread/read",
    "thread/start",
    "thread/fork",
    "thread/rollback",
    "thread/archive",
    "thread/unarchive",
    "thread/delete",
    "thread/inject_items",
    "thread/name/set",
    "thread/loaded/list",
    "thread/turns/list",
]
THREADS = {
    "root": {
        "id": "root",
        "name": "Old root",
        "cwd": "/tmp/project",
        "updatedAt": "2025-01-01T00:00:00Z",
        "status": {"type": "idle"},
        "turns": [
            {
                "id": "root-turn",
                "status": "completed",
                "items": [
                    {
                        "id": "root-message",
                        "type": "agentMessage",
                        "role": "assistant",
                        "text": "root content",
                    }
                ],
            }
        ],
    },
    "child": {
        "id": "child",
        "name": "Old child",
        "cwd": "/tmp/project",
        "updatedAt": "2025-01-02T00:00:00Z",
        "status": {"type": "idle"},
        "parentThreadId": "root",
        "turns": [
            {
                "id": "child-turn",
                "status": "completed",
                "items": [
                    {
                        "id": "child-message",
                        "type": "agentMessage",
                        "role": "assistant",
                        "text": "child content",
                    }
                ],
            }
        ],
    },
    "archived": {
        "id": "archived",
        "name": "Archived task",
        "cwd": "/tmp/archive",
        "updatedAt": "2024-01-01T00:00:00Z",
        "status": {"type": "idle"},
        "turns": [],
    },
}

STATE_PATH = os.environ.get("CSM_FAKE_STATE")
if STATE_PATH and Path(STATE_PATH).is_file():
    THREADS = json.loads(Path(STATE_PATH).read_text(encoding="utf-8"))


def save_state():
    if STATE_PATH:
        Path(STATE_PATH).write_text(
            json.dumps(THREADS, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )


def derived_id():
    count = sum(thread_id.startswith("derived-") for thread_id in THREADS)
    return f"derived-{count + 1}"


def log(value):
    destination = os.environ.get("CSM_FAKE_APP_SERVER_LOG")
    if not destination:
        return
    with open(destination, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def generate_schema():
    output = Path(sys.argv[sys.argv.index("--out") + 1])
    output.mkdir(parents=True, exist_ok=True)
    schema = {
        "definitions": {
            "ClientRequestMethod": {
                "title": "ClientRequestMethod",
                "enum": METHODS,
            },
            "ThreadForkParams": {
                "type": "object",
                "properties": {"threadId": {"type": "string"}},
            },
        }
    }
    (output / "ClientRequest.json").write_text(
        json.dumps(schema, sort_keys=True), encoding="utf-8"
    )
    turn = {
        "type": "object",
        "required": ["id", "status", "items"],
        "properties": {
            "id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["completed", "interrupted", "failed", "inProgress"],
            },
            "items": {"type": "array", "items": {"type": "object"}},
        },
    }
    thread = {
        "type": "object",
        "required": ["id", "status", "createdAt", "updatedAt", "ephemeral", "turns"],
        "properties": {
            "id": {"type": "string"},
            "createdAt": {"type": ["integer", "null"]},
            "updatedAt": {"type": ["integer", "null"]},
            "status": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["notLoaded", "idle", "active", "systemError"],
                    }
                },
            },
            "parentThreadId": {"type": ["string", "null"]},
            "forkedFromId": {"type": ["string", "null"]},
            "sessionId": {"type": ["string", "null"]},
            "ephemeral": {"type": "boolean"},
            "historyMode": {"type": "string", "enum": ["legacy", "paginated"]},
            "turns": {"type": "array", "items": {"$ref": "#/definitions/Turn"}},
        },
    }

    def write_document(name, value):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    common_documents = {
        "v2/ThreadListParams.json": {
            "title": "ThreadListParams",
            "type": "object",
            "properties": {
                "archived": {"type": ["boolean", "null"]},
                "cursor": {"type": ["string", "null"]},
                "limit": {"type": ["integer", "null"]},
                "sourceKinds": {"type": "array", "items": {"type": "string"}},
                "useStateDbOnly": {"type": "boolean"},
            },
        },
        "v2/ThreadReadParams.json": {
            "title": "ThreadReadParams",
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {"type": "string"}, "includeTurns": {"type": "boolean"}},
        },
        "v2/ThreadLoadedListParams.json": {
            "title": "ThreadLoadedListParams",
            "type": "object",
            "properties": {
                "cursor": {"type": ["string", "null"]},
                "limit": {"type": ["integer", "null"]},
            },
        },
        "v2/ThreadArchiveParams.json": {
            "title": "ThreadArchiveParams",
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {"type": "string"}},
        },
        "v2/ThreadUnarchiveParams.json": {
            "title": "ThreadUnarchiveParams",
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {"type": "string"}},
        },
        "v2/ThreadListResponse.json": {
            "title": "ThreadListResponse",
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array", "items": {"$ref": "#/definitions/Thread"}},
                "nextCursor": {"type": ["string", "null"]},
            },
            "definitions": {"Thread": thread, "Turn": turn},
        },
        "v2/ThreadReadResponse.json": {
            "title": "ThreadReadResponse",
            "type": "object",
            "required": ["thread"],
            "properties": {"thread": {"$ref": "#/definitions/Thread"}},
            "definitions": {"Thread": thread, "Turn": turn},
        },
        "v2/ThreadLoadedListResponse.json": {
            "title": "ThreadLoadedListResponse",
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": {"type": "string"}},
                "threadIds": {"type": "array", "items": {"type": "string"}},
            },
        },
        "v2/ThreadArchiveResponse.json": {"title": "ThreadArchiveResponse", "type": "object"},
        "v2/ThreadUnarchiveResponse.json": {
            "title": "ThreadUnarchiveResponse",
            "type": "object",
        },
        "v2/ThreadArchivedNotification.json": {
            "title": "ThreadArchivedNotification",
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {"type": "string"}},
        },
        "v2/ThreadUnarchivedNotification.json": {
            "title": "ThreadUnarchivedNotification",
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {"type": "string"}},
        },
        "v2/ThreadTurnsListParams.json": {
            "title": "ThreadTurnsListParams",
            "type": "object",
            "required": ["threadId"],
            "properties": {
                "threadId": {"type": "string"},
                "cursor": {"type": ["string", "null"]},
                "limit": {"type": ["integer", "null"]},
                "sortDirection": {"type": "string", "enum": ["asc", "desc"]},
                "itemsView": {"type": "string", "enum": ["full", "summary"]},
            },
        },
        "v2/ThreadTurnsListResponse.json": {
            "title": "ThreadTurnsListResponse",
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array", "items": {"$ref": "#/definitions/Turn"}},
                "nextCursor": {"type": ["string", "null"]},
            },
            "definitions": {"Turn": turn},
        },
    }
    for name, document in common_documents.items():
        write_document(name, document)


def summary(thread_id):
    value = dict(THREADS[thread_id])
    value.pop("turns", None)
    return value


def run_server():
    for line in sys.stdin:
        message = json.loads(line)
        log({"codex_home": os.environ.get("CODEX_HOME"), "message": message})
        request_id = message.get("id")
        if request_id is None:
            continue
        method = message.get("method")
        params = message.get("params", {})
        if method == "initialize":
            emit({"method": "server/ready", "params": {"fixture": True}})
            emit({"id": request_id, "result": {"serverInfo": {"name": "fake-codex"}}})
        elif method == "thread/list":
            if params.get("archived"):
                result = {"data": [summary("archived")], "nextCursor": None}
            elif params.get("cursor") == "page-2":
                result = {"data": [summary("child")], "nextCursor": None}
            else:
                result = {"data": [summary("root")], "nextCursor": "page-2"}
            emit({"id": request_id, "result": result})
        elif method == "thread/read":
            thread_id = params.get("threadId")
            emit({"id": request_id, "result": {"thread": THREADS[thread_id]}})
        elif method == "thread/start":
            thread_id = derived_id()
            THREADS[thread_id] = {
                "id": thread_id,
                "name": "Derived task",
                "cwd": params.get("cwd"),
                "updatedAt": "2026-08-13T00:00:00Z",
                "status": {"type": "idle"},
                "turns": [],
            }
            save_state()
            emit({"id": request_id, "result": {"thread": THREADS[thread_id]}})
        elif method == "thread/fork":
            source_id = params.get("threadId")
            thread_id = derived_id()
            derived = json.loads(json.dumps(THREADS[source_id]))
            derived["id"] = thread_id
            derived["name"] = derived.get("name", source_id) + " · fork"
            derived["forkedFromId"] = source_id
            THREADS[thread_id] = derived
            save_state()
            emit({"id": request_id, "result": {"thread": derived}})
        elif method == "thread/rollback":
            thread_id = params.get("threadId")
            num_turns = int(params.get("numTurns", 0))
            if num_turns:
                THREADS[thread_id]["turns"] = THREADS[thread_id]["turns"][:-num_turns]
            save_state()
            emit({"id": request_id, "result": {"thread": THREADS[thread_id]}})
        elif method == "thread/inject_items":
            thread_id = params.get("threadId")
            for index, item in enumerate(params.get("items", []), start=1):
                content = item.get("content", [])
                text = "\n".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
                THREADS[thread_id]["turns"].append(
                    {
                        "id": f"injected-{index}",
                        "status": "completed",
                        "items": [
                            {
                                "id": f"injected-message-{index}",
                                "type": "agentMessage",
                                "role": "assistant",
                                "text": text,
                            }
                        ],
                    }
                )
            save_state()
            emit({"id": request_id, "result": {}})
        elif method == "thread/name/set":
            THREADS[params.get("threadId")]["name"] = params.get("name")
            save_state()
            emit({"id": request_id, "result": {}})
        elif method == "thread/archive":
            THREADS[params.get("threadId")]["archived"] = True
            save_state()
            emit({"id": request_id, "result": {}})
        elif method == "thread/unarchive":
            THREADS[params.get("threadId")]["archived"] = False
            save_state()
            emit({"id": request_id, "result": {"thread": THREADS[params.get("threadId")]}})
        elif method == "thread/delete":
            THREADS.pop(params.get("threadId"), None)
            save_state()
            emit({"id": request_id, "result": {}})
        elif method == "thread/loaded/list":
            emit({"id": request_id, "result": {"data": []}})
        else:
            emit(
                {
                    "id": request_id,
                    "error": {"code": -32601, "message": f"unsupported: {method}"},
                }
            )


if sys.argv[1:] == ["--version"]:
    print("codex-cli 9.9.9")
elif len(sys.argv) >= 3 and sys.argv[1:3] == ["app-server", "generate-json-schema"]:
    generate_schema()
elif sys.argv[1:4] == ["app-server", "--listen", "stdio://"]:
    run_server()
else:
    raise SystemExit(f"unexpected fake codex arguments: {sys.argv[1:]}")
"""


def _fake_codex(tmp_path: Path) -> Path:
    if os.name == "nt":
        source = tmp_path / "fake-codex.py"
        source.write_text(FAKE_CODEX_SOURCE, encoding="utf-8")
        executable = tmp_path / "fake-codex.cmd"
        executable.write_text(
            f'@"{sys.executable}" "{source}" %*\r\n',
            encoding="utf-8",
        )
    else:
        executable = tmp_path / "fake-codex"
        executable.write_text(f"#!{sys.executable}\n{FAKE_CODEX_SOURCE}", encoding="utf-8")
    executable.chmod(0o700)
    return executable


def _isolated_environment(tmp_path: Path, executable: Path) -> dict[str, str]:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    return {
        "CODEX_HOME": str(codex_home),
        "CSM_CODEX_HOME": str(codex_home),
        "CSM_CODEX_BIN": str(executable),
        "CSM_DATA_DIR": str(tmp_path / "data"),
        "CSM_CONFIG_DIR": str(tmp_path / "config"),
        "CSM_CACHE_DIR": str(tmp_path / "cache"),
        "CSM_LOG_DIR": str(tmp_path / "log"),
        "CSM_FAKE_APP_SERVER_LOG": str(tmp_path / "app-server.jsonl"),
        "CSM_FAKE_STATE": str(tmp_path / "fake-state.json"),
    }


def _run_cli(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    subprocess_environment = os.environ.copy() | environment
    existing_python_path = subprocess_environment.get("PYTHONPATH")
    subprocess_environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(PROJECT_ROOT / "src"), existing_python_path) if value
    )
    return subprocess.run(
        [sys.executable, "-m", "codex_session_manager.cli", *arguments],
        capture_output=True,
        text=True,
        env=subprocess_environment,
        check=False,
        timeout=10,
    )


def test_process_app_server_initializes_paginates_and_normalizes_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _fake_codex(tmp_path)
    environment = _isolated_environment(tmp_path, executable)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    client, capabilities = connect_and_probe(executable=str(executable), request_timeout=3)
    try:
        snapshots = InventoryService(client).list(include_turns=True)
        notifications = client.drain_notifications()
    finally:
        client.close()

    assert capabilities.schema_complete
    assert capabilities.probe_error is None
    assert {capability.operation for capability in capabilities.operation_capabilities} == set(
        OperationName
    )
    assert all(capability.available for capability in capabilities.operation_capabilities)
    assert [snapshot.id for snapshot in snapshots] == ["archived", "child", "root"]
    root = next(snapshot for snapshot in snapshots if snapshot.id == "root")
    assert root.spawned_descendant_ids == ("child",)
    assert all(snapshot.content_complete for snapshot in snapshots)
    assert any(notification.get("method") == "server/ready" for notification in notifications)

    records = [
        json.loads(line)
        for line in Path(environment["CSM_FAKE_APP_SERVER_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    messages = [record["message"] for record in records if "message" in record]
    assert messages[0]["method"] == "initialize"
    assert messages[0]["params"]["clientInfo"]["version"] == __version__
    assert any(message.get("method") == "initialized" for message in messages)
    assert any(
        message.get("method") == "thread/list"
        and message.get("params", {}).get("cursor") == "page-2"
        for message in messages
    )
    assert all(record.get("codex_home") == environment["CODEX_HOME"] for record in records)


def test_cli_reads_and_builds_a_sealed_plan_without_app_server_writes(
    tmp_path: Path,
) -> None:
    executable = _fake_codex(tmp_path)
    environment = _isolated_environment(tmp_path, executable)

    listed = _run_cli(environment, "threads", "list")
    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["count"] == 3

    planned = _run_cli(
        environment,
        "cleanup",
        "plan",
        "--action",
        "archive",
        "--older-than-days",
        "90",
    )
    assert planned.returncode == 0, planned.stderr
    planned_payload = json.loads(planned.stdout)
    assert planned_payload["plan"]["action"] == "archive"
    assert Path(planned_payload["path"]).is_file()
    assert {target["root_thread_id"] for target in planned_payload["plan"]["targets"]} == {"root"}

    records = [
        json.loads(line)
        for line in Path(environment["CSM_FAKE_APP_SERVER_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    methods = {
        record["message"].get("method")
        for record in records
        if isinstance(record.get("message"), dict)
    }
    assert not methods & {
        "thread/archive",
        "thread/delete",
        "thread/fork",
        "thread/inject_items",
        "thread/start",
        "thread/unarchive",
    }


def test_cli_derived_trim_fails_closed_without_app_server_writes(tmp_path: Path) -> None:
    executable = _fake_codex(tmp_path)
    environment = _isolated_environment(tmp_path, executable)

    suggested = _run_cli(environment, "trim", "suggest", "root")
    assert suggested.returncode == 0, suggested.stderr
    suggested_payload = json.loads(suggested.stdout)
    plan = suggested_payload["plan"]

    applied = _run_cli(
        environment,
        "trim",
        "apply",
        suggested_payload["path"],
        "--confirm",
        plan["plan_id"],
    )

    assert applied.returncode != 0
    assert "no approved operation contract" in (applied.stderr + applied.stdout)
    records = [
        json.loads(line)
        for line in Path(environment["CSM_FAKE_APP_SERVER_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    methods = {
        record["message"].get("method")
        for record in records
        if isinstance(record.get("message"), dict)
    }
    assert not methods & {
        "thread/fork",
        "thread/rollback",
        "thread/start",
        "thread/inject_items",
        "thread/name/set",
    }
