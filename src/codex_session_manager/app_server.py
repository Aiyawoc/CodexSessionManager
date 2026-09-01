"""Synchronous stdio client for the official Codex App Server.

The client never opens Codex rollout JSONL files or SQLite databases for
mutation.  It serializes requests over one connection so an ambiguous timeout
can be surfaced to the caller instead of being retried blindly.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final, Self

from codex_session_manager.config import codex_binary, get_paths
from codex_session_manager.hashing import canonical_json_bytes, fingerprint, hash_file, sha256_bytes
from codex_session_manager.models import CapabilityMatrix
from codex_session_manager.operation_contracts import evaluate_operation_contracts
from codex_session_manager.version import __version__

LOGGER = logging.getLogger(__name__)

BASELINE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "initialize",
        "thread/list",
        "thread/read",
        "thread/loaded/list",
    }
)
ALL_SOURCE_KINDS: Final[tuple[str, ...]] = (
    "cli",
    "vscode",
    "exec",
    "appServer",
    "subAgent",
    "subAgentReview",
    "subAgentCompact",
    "subAgentThreadSpawn",
    "subAgentOther",
    "unknown",
)
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "thread/start",
        "thread/fork",
        "thread/archive",
        "thread/unarchive",
        "thread/delete",
        "thread/inject_items",
        "thread/name/set",
    }
)


class AppServerError(RuntimeError):
    """Base error for transport and JSON-RPC failures."""


class ProtocolError(AppServerError):
    """The server emitted malformed or incompatible protocol data."""


class RequestError(AppServerError):
    """A JSON-RPC response contained an error object.

    Write handlers may return an error after mutating an earlier persistence
    layer, so callers must reconcile actual state before deciding to retry.
    """

    def __init__(self, method: str, error: dict[str, Any]) -> None:
        self.method = method
        self.code = error.get("code")
        self.data = error.get("data")
        self.message = str(error.get("message", "unknown App Server error"))
        self.may_have_committed = method in WRITE_METHODS
        super().__init__(f"{method} failed ({self.code}): {self.message}")


class RequestTimeout(AppServerError):
    """A request timed out; write methods may already have committed."""

    def __init__(self, method: str, timeout: float) -> None:
        self.method = method
        self.timeout = timeout
        self.may_have_committed = method in WRITE_METHODS
        suffix = "; query actual state before any retry" if self.may_have_committed else ""
        super().__init__(f"{method} timed out after {timeout:.1f}s{suffix}")


class SubprocessAppServer:
    """One serialized App Server stdio connection."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        request_timeout: float = 30.0,
        experimental: bool = False,
    ) -> None:
        self.executable = executable or codex_binary()
        self.request_timeout = request_timeout
        self.experimental = experimental
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._pending: dict[int, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._request_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self.initialize_result: dict[str, Any] | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            codex_home = get_paths().codex_home.expanduser().resolve(strict=False)
        except ValueError as exc:
            raise AppServerError(str(exc)) from exc
        inherited_codex_home = os.environ.get("CODEX_HOME")
        if inherited_codex_home is not None:
            inherited = Path(inherited_codex_home).expanduser().resolve(strict=False)
            if inherited != codex_home:
                raise AppServerError(
                    "CODEX_HOME and CSM_CODEX_HOME resolve to different Codex data roots; "
                    "refusing to mix accounts"
                )
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
        try:
            self._process = subprocess.Popen(
                [self.executable, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
            )
        except OSError as exc:
            self._process = None
            raise AppServerError(f"unable to start Codex App Server: {exc}") from exc
        try:
            threading.Thread(
                target=self._read_stdout, name="csm-app-server-reader", daemon=True
            ).start()
            threading.Thread(
                target=self._read_stderr, name="csm-app-server-stderr", daemon=True
            ).start()
            capabilities: dict[str, Any] = {
                "optOutNotificationMethods": [
                    "item/agentMessage/delta",
                    "item/reasoning/textDelta",
                    "item/reasoning/summaryTextDelta",
                ]
            }
            if self.experimental:
                capabilities["experimentalApi"] = True
            result = self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_session_manager",
                        "title": "CodexSessionManager",
                        "version": __version__,
                    },
                    "capabilities": capabilities,
                },
            )
            if not isinstance(result, dict):
                raise ProtocolError("initialize result must be an object")
            self.initialize_result = result
            self.notify("initialized", {})
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    message = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    self._messages.put(ProtocolError(f"invalid App Server JSON: {exc}"))
                    continue
                if not isinstance(message, dict):
                    self._messages.put(ProtocolError("App Server message must be an object"))
                    continue
                self._messages.put(message)
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            self._messages.put(exc)
        finally:
            self._messages.put(ProtocolError("App Server stdout closed"))

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            LOGGER.debug("app-server stderr: %s", line.rstrip())

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise AppServerError("App Server is not running")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                process.stdin.write(encoded + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise AppServerError("failed to write to App Server") from exc

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send one request and wait for its matching response."""

        effective_timeout = timeout if timeout is not None else self.request_timeout
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            self._send({"method": method, "id": request_id, "params": params or {}})
            if request_id in self._pending:
                response = self._pending.pop(request_id)
            else:
                response = self._wait_for_response(request_id, effective_timeout, method)
            if "error" in response:
                error = response["error"]
                if not isinstance(error, dict):
                    raise ProtocolError(f"{method} error must be an object")
                raise RequestError(method, error)
            if "result" not in response:
                raise ProtocolError(f"{method} response lacks result/error")
            return response["result"]

    def _wait_for_response(self, request_id: int, timeout: float, method: str) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(method, timeout)
            try:
                message = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise RequestTimeout(method, timeout) from exc
            if isinstance(message, BaseException):
                raise AppServerError(str(message)) from message
            message_id = message.get("id")
            if message_id == request_id and ("result" in message or "error" in message):
                return message
            if isinstance(message_id, int) and ("result" in message or "error" in message):
                self._pending[message_id] = message
            elif message_id is not None and "method" in message:
                # CSM does not opt into server-initiated capabilities.  Reply so
                # an unexpected request cannot deadlock the server.
                self._send(
                    {
                        "id": message_id,
                        "error": {"code": -32601, "message": "client method not supported"},
                    }
                )
            else:
                self._notifications.append(message)

    def drain_notifications(self) -> tuple[dict[str, Any], ...]:
        notifications = tuple(self._notifications)
        self._notifications.clear()
        return notifications

    def list_threads(
        self,
        *,
        archived: bool = False,
        limit: int = 100,
        source_kinds: tuple[str, ...] = ALL_SOURCE_KINDS,
        cwd: str | None = None,
        search_term: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "archived": archived,
                "limit": limit,
                "useStateDbOnly": True,
            }
            if cursor:
                params["cursor"] = cursor
            params["sourceKinds"] = list(source_kinds)
            if cwd:
                params["cwd"] = cwd
            if search_term:
                params["searchTerm"] = search_term
            result = self.request("thread/list", params)
            if not isinstance(result, dict):
                raise ProtocolError("thread/list result must be an object")
            data = result.get("data", [])
            if not isinstance(data, list):
                raise ProtocolError("thread/list data must be an array")
            for thread in data:
                if not isinstance(thread, dict):
                    raise ProtocolError("thread/list entry must be an object")
                yield thread
            cursor_value = result.get("nextCursor")
            cursor = cursor_value if isinstance(cursor_value, str) and cursor_value else None
            if cursor is None:
                return

    def read_thread(self, thread_id: str, *, include_turns: bool = False) -> dict[str, Any]:
        result = self.request("thread/read", {"threadId": thread_id, "includeTurns": include_turns})
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise ProtocolError("thread/read result lacks thread")
        thread = dict(result["thread"])
        if thread.get("id") != thread_id:
            raise ProtocolError("thread/read returned a different thread id")
        return thread

    def loaded_thread_ids(self) -> tuple[str, ...]:
        result = self.request("thread/loaded/list", {})
        if not isinstance(result, dict):
            raise ProtocolError("thread/loaded/list result must be an object")
        data = result.get("data", result.get("threadIds", []))
        if not isinstance(data, list):
            raise ProtocolError("thread/loaded/list data must be an array")
        ids: list[str] = []
        for item in data:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.append(item["id"])
        return tuple(ids)

    def archive_thread(self, thread_id: str) -> None:
        self.request("thread/archive", {"threadId": thread_id})

    def unarchive_thread(self, thread_id: str) -> dict[str, Any]:
        result = self.request("thread/unarchive", {"threadId": thread_id})
        if not isinstance(result, dict):
            raise ProtocolError("thread/unarchive result must be an object")
        return result

    def delete_thread(self, thread_id: str) -> None:
        self.request("thread/delete", {"threadId": thread_id})

    def rename_thread(self, thread_id: str, name: str) -> None:
        if not name.strip():
            raise ValueError("thread name must not be empty")
        self.request("thread/name/set", {"threadId": thread_id, "name": name})

    def start_thread(self, *, cwd: str | None = None, name: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if cwd:
            params["cwd"] = cwd
        result = self.request("thread/start", params)
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise ProtocolError("thread/start result lacks thread")
        thread = dict(result["thread"])
        if not isinstance(thread.get("id"), str) or not thread["id"]:
            raise ProtocolError("thread/start returned no non-empty thread id")
        if name:
            self.rename_thread(thread["id"], name)
        return thread

    def fork_thread(self, thread_id: str, *, last_turn_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id}
        if last_turn_id:
            params["lastTurnId"] = last_turn_id
        result = self.request("thread/fork", params)
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise ProtocolError("thread/fork result lacks thread")
        thread = dict(result["thread"])
        derived_id = thread.get("id")
        if not isinstance(derived_id, str) or not derived_id or derived_id == thread_id:
            raise ProtocolError("thread/fork returned an invalid derived thread id")
        return thread

    def rollback_thread(self, thread_id: str, *, num_turns: int) -> dict[str, Any]:
        if num_turns < 1:
            raise ValueError("num_turns must be at least one")
        result = self.request("thread/rollback", {"threadId": thread_id, "numTurns": num_turns})
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise ProtocolError("thread/rollback result lacks thread")
        thread = dict(result["thread"])
        if thread.get("id") != thread_id:
            raise ProtocolError("thread/rollback returned a different thread id")
        return thread

    def background_terminals(self, thread_id: str) -> tuple[dict[str, Any], ...]:
        result = self.request(
            "thread/backgroundTerminals/list", {"threadId": thread_id, "limit": 1000}
        )
        if not isinstance(result, dict):
            raise ProtocolError("thread/backgroundTerminals/list result must be an object")
        data = result.get("data", result.get("terminals", []))
        if not isinstance(data, list):
            raise ProtocolError("thread/backgroundTerminals/list data must be an array")
        return tuple(dict(item) for item in data if isinstance(item, dict))

    def inject_items(self, thread_id: str, items: list[dict[str, Any]]) -> None:
        result = self.request("thread/inject_items", {"threadId": thread_id, "items": items})
        if not isinstance(result, dict):
            raise ProtocolError("thread/inject_items result must be an object")


def _extract_methods(schema: Any) -> set[str]:
    methods: set[str] = set()
    if isinstance(schema, dict):
        title = schema.get("title")
        if isinstance(title, str) and title.endswith("RequestMethod"):
            enum = schema.get("enum")
            if isinstance(enum, list):
                methods.update(value for value in enum if isinstance(value, str))
        for value in schema.values():
            methods.update(_extract_methods(value))
    elif isinstance(schema, list):
        for value in schema:
            methods.update(_extract_methods(value))
    return methods


def _generate_schema(
    executable: str, output: Path, *, experimental: bool
) -> tuple[dict[str, dict[str, Any]], set[str], str]:
    command = [executable, "app-server", "generate-json-schema"]
    if experimental:
        command.append("--experimental")
    command.extend(["--out", str(output)])
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    documents: dict[str, dict[str, Any]] = {}
    digest_parts = bytearray()
    for path in sorted(output.rglob("*.json")):
        relative_path = path.relative_to(output).as_posix()
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ProtocolError(f"generated schema document is not an object: {relative_path}")
        documents[relative_path] = document
        if relative_path == "ClientRequest.json":
            methods = _extract_methods(document)
        digest_parts.extend(relative_path.encode("utf-8"))
        digest_parts.extend(b"\0")
        # The generator may emit semantically identical object keys in a
        # different order between processes. Hash canonical JSON so a plan is
        # invalidated only by a real schema change.
        digest_parts.extend(canonical_json_bytes(document))
        digest_parts.extend(b"\0")
    if "ClientRequest.json" not in documents:
        raise ProtocolError("generated schema lacks ClientRequest.json")
    methods = _extract_methods(documents["ClientRequest.json"])
    return documents, methods, sha256_bytes(bytes(digest_parts))


def _definition_has_property(schema: dict[str, Any], definition: str, field: str) -> bool:
    definitions = schema.get("definitions")
    if not isinstance(definitions, dict):
        return False
    value = definitions.get(definition)
    if not isinstance(value, dict):
        return False
    properties = value.get("properties")
    return isinstance(properties, dict) and field in properties


def _codex_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\b\d+\.\d+(?:\.\d+)?(?:[-+][\w.-]+)?\b", completed.stdout)
    return match.group(0) if match else completed.stdout.strip() or None


def probe_capabilities(
    *,
    executable: str | None = None,
    initialize_result: dict[str, Any] | None = None,
    experimental_api: bool = False,
) -> CapabilityMatrix:
    """Generate local schemas and derive independently fail-closed contracts."""

    binary = executable or codex_binary()
    init_result = initialize_result or {}
    init_fingerprint = fingerprint(init_result)
    try:
        with tempfile.TemporaryDirectory(prefix="csm-app-server-schema-") as temp:
            root = Path(temp)
            stable_dir = root / "stable"
            experimental_dir = root / "experimental"
            stable_dir.mkdir()
            experimental_dir.mkdir()
            stable_documents, stable_methods, stable_hash = _generate_schema(
                binary, stable_dir, experimental=False
            )
            experimental_documents, experimental_methods, experimental_hash = _generate_schema(
                binary, experimental_dir, experimental=True
            )
            operation_capabilities = evaluate_operation_contracts(
                stable_documents=stable_documents,
                experimental_documents=experimental_documents,
                stable_methods=stable_methods,
                experimental_methods=experimental_methods,
                experimental_api=experimental_api,
            )
        resolved_binary = Path(shutil.which(binary) or binary).resolve(strict=True)
        binary_sha256, _binary_size = hash_file(resolved_binary)
        codex_version = _codex_version(binary)
        schema_sha256 = sha256_bytes(f"{stable_hash}:{experimental_hash}".encode())
        return CapabilityMatrix(
            codex_version=codex_version,
            codex_binary_path=str(resolved_binary),
            codex_binary_sha256=binary_sha256,
            initialize_fingerprint=init_fingerprint,
            schema_sha256=schema_sha256,
            stable_methods=tuple(sorted(stable_methods)),
            experimental_methods=tuple(sorted(experimental_methods - stable_methods)),
            experimental_api=experimental_api,
            fork_supports_last_turn_id=_definition_has_property(
                stable_documents["ClientRequest.json"], "ThreadForkParams", "lastTurnId"
            ),
            schema_complete=True,
            operation_capabilities=operation_capabilities,
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ProtocolError) as exc:
        return CapabilityMatrix(
            codex_version=_codex_version(binary),
            initialize_fingerprint=init_fingerprint,
            schema_complete=False,
            operation_capabilities=evaluate_operation_contracts(
                stable_documents={},
                experimental_documents={},
                stable_methods=set(),
                experimental_methods=set(),
                experimental_api=experimental_api,
            ),
            probe_error=str(exc),
        )


def connect_and_probe(
    *,
    executable: str | None = None,
    request_timeout: float = 30.0,
    experimental_api: bool = False,
) -> tuple[SubprocessAppServer, CapabilityMatrix]:
    """Start an initialized client and probe its exact local schema."""

    client = SubprocessAppServer(
        executable=executable,
        request_timeout=request_timeout,
        experimental=experimental_api,
    )
    try:
        client.start()
        capabilities = probe_capabilities(
            executable=client.executable,
            initialize_result=client.initialize_result,
            experimental_api=experimental_api,
        )
        return client, capabilities
    except BaseException:
        client.close()
        raise
