from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.inventory import InventoryService
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
    assert not capabilities.write_enabled
    assert "audited write allowlist" in (capabilities.read_only_reason or "")
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


FULL_CLI_WORKFLOW_DRIVER = r"""
import json

from typer.testing import CliRunner

import codex_session_manager.app_server as app_server
import codex_session_manager.protocol_profiles as protocol_profiles

probe = app_server.probe_capabilities()
if not probe.schema_sha256 or not probe.codex_version:
    raise RuntimeError("fake schema probe failed")
# Test-process-only approval: production has no environment or CLI switch that
# can expand the bundled human-reviewed protocol allowlist.
app_server.TRUSTED_WRITE_SCHEMAS = frozenset(
    {(probe.codex_version, probe.schema_sha256)}
)
protocol_profiles.TRUSTED_WRITE_SCHEMAS = frozenset(
    {(probe.codex_version, probe.schema_sha256)}
)

from codex_session_manager.cli import app

runner = CliRunner()


def invoke(*arguments):
    result = runner.invoke(app, list(arguments))
    if result.exit_code != 0:
        raise RuntimeError(f"CLI failed {arguments}: {result.output}\n{result.exception}")
    return json.loads(result.stdout)


source_before = invoke("threads", "show", "root", "--include-content")["thread"]
suggested = invoke("trim", "suggest", "root")
plan = suggested["plan"]
applied = invoke(
    "trim",
    "apply",
    suggested["path"],
    "--confirm",
    plan["plan_id"],
)
derived_id = applied["derived_thread_id"]
derived = invoke("threads", "show", derived_id, "--include-content")["thread"]
source_after = invoke("threads", "show", "root", "--include-content")["thread"]
if source_after["turns"] != source_before["turns"]:
    raise RuntimeError("source task changed during derived trim")
if derived["turns"] != source_before["turns"]:
    raise RuntimeError("derived prefix does not match the source")
print(
    json.dumps(
        {
            "source_id": source_after["id"],
            "derived_id": derived_id,
            "plan_sha256": plan["plan_sha256"],
            "source_preserved": True,
        },
        sort_keys=True,
    )
)
"""


def test_full_cli_subprocess_creates_verified_derived_task_and_preserves_source(
    tmp_path: Path,
) -> None:
    executable = _fake_codex(tmp_path)
    environment = os.environ.copy() | _isolated_environment(tmp_path, executable)
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(PROJECT_ROOT / "src"), existing_python_path) if value
    )

    completed = subprocess.run(
        [sys.executable, "-c", FULL_CLI_WORKFLOW_DRIVER],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["source_id"] == "root"
    assert result["derived_id"].startswith("derived-")
    assert result["source_preserved"] is True
    assert len(result["plan_sha256"]) == 64
    records = [
        json.loads(line)
        for line in Path(environment["CSM_FAKE_APP_SERVER_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    methods = [
        record["message"].get("method")
        for record in records
        if isinstance(record.get("message"), dict)
    ]
    assert methods.count("thread/fork") == 1
    assert "thread/delete" not in methods
