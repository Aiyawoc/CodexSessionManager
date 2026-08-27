"""Minimal stateless MCP Streamable HTTP server for read-only CSM orchestration.

The server deliberately exposes no Codex write executor.  Tools may inspect
metadata, persist immutable suggestion/review files, query their status, and
ask the local desktop application to open a human review window.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Final, cast

from pydantic import BaseModel

from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.mcp_bridge import (
    CleanupSuggestionInput,
    ContextSuggestionInput,
    MemorySuggestionInput,
    ReviewLauncher,
    get_pending_review_status,
    inspect_conversation_inventory,
    inspect_memory_source,
    open_review_demo,
    open_sealed_review,
    prepare_cleanup_suggestions_from_current,
    prepare_context_suggestions_from_current,
    prepare_memory_review,
)
from codex_session_manager.review_requests import ReviewOperation
from codex_session_manager.version import __version__

SUPPORTED_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = (
    "2025-11-25",
    "2025-06-18",
)
DEFAULT_PROTOCOL_VERSION: Final[str] = SUPPORTED_PROTOCOL_VERSIONS[0]
MAX_REQUEST_BYTES: Final[int] = 1024 * 1024

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], Any]


class MethodNotFoundError(ValueError):
    """JSON-RPC method lookup failed without implying invalid parameters."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    title: str
    description: str
    input_schema: JsonObject
    handler: ToolHandler
    read_only: bool
    idempotent: bool

    def descriptor(self) -> JsonObject:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.idempotent,
                "openWorldHint": False,
            },
        }


class McpApplication:
    """Pure JSON-RPC dispatcher used by both HTTP transport and unit tests."""

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        launcher: ReviewLauncher | None = None,
    ) -> None:
        self.paths = paths or get_paths()
        self.paths.ensure()
        self.launcher = launcher
        self.tools = {tool.name: tool for tool in self._build_tools()}

    def _build_tools(self) -> tuple[McpTool, ...]:
        suggestion_item = {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["target_id", "reason", "confidence"],
            "additionalProperties": False,
        }
        context_item = {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1},
                "suggested_action": {
                    "type": "string",
                    "enum": ["keep", "exclude", "summary", "protect"],
                },
                "reason": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "suggested_text": {"type": ["string", "null"]},
            },
            "required": ["target_id", "suggested_action", "reason", "confidence"],
            "additionalProperties": False,
        }
        memory_item = {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1},
                "suggested_action": {
                    "type": "string",
                    "enum": ["keep", "delete", "replace", "protect"],
                },
                "reason": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "suggested_text": {"type": ["string", "null"]},
            },
            "required": ["target_id", "suggested_action", "reason", "confidence"],
            "additionalProperties": False,
        }
        request_id_schema = {
            "type": "object",
            "properties": {"request_id": {"type": "string", "minLength": 1, "maxLength": 128}},
            "required": ["request_id"],
            "additionalProperties": False,
        }
        return (
            McpTool(
                name="inspect_conversation_inventory",
                title="Inspect safe cleanup candidates",
                description=(
                    "Return bounded metadata for locally safe, inactive Codex cleanup roots. "
                    "Conversation content is never returned."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "older_than_days": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 90,
                        }
                    },
                    "additionalProperties": False,
                },
                handler=self._inspect_inventory,
                read_only=True,
                idempotent=True,
            ),
            McpTool(
                name="prepare_cleanup_suggestions",
                title="Prepare cleanup review",
                description=(
                    "Locally validate an LLM shortlist against current safe roots, bind current "
                    "fingerprints, and persist an immutable human review request."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "older_than_days": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 90,
                        },
                        "suggestions": {"type": "array", "items": suggestion_item},
                    },
                    "required": ["suggestions"],
                    "additionalProperties": False,
                },
                handler=self._prepare_cleanup,
                read_only=False,
                idempotent=False,
            ),
            McpTool(
                name="open_cleanup_review",
                title="Open cleanup review",
                description=(
                    "Validate a sealed cleanup request, queue it, and open the original local GUI "
                    "for final human selection. No archive is executed."
                ),
                input_schema=request_id_schema,
                handler=self._open_cleanup,
                read_only=False,
                idempotent=True,
            ),
            McpTool(
                name="prepare_context_suggestions",
                title="Prepare context review",
                description=(
                    "Bind an LLM turn/item shortlist to current local fingerprints and hard "
                    "protection, then persist an immutable context review request."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "minLength": 1},
                        "suggestions": {"type": "array", "items": context_item},
                    },
                    "required": ["thread_id", "suggestions"],
                    "additionalProperties": False,
                },
                handler=self._prepare_context,
                read_only=False,
                idempotent=False,
            ),
            McpTool(
                name="open_context_review",
                title="Open context review",
                description=(
                    "Validate a sealed context request, queue it, and open the original local GUI. "
                    "No derived task is created by this tool."
                ),
                input_schema=request_id_schema,
                handler=self._open_context,
                read_only=False,
                idempotent=True,
            ),
            McpTool(
                name="inspect_memory_source",
                title="Inspect a registered memory source",
                description=(
                    "Return stable segment IDs, fingerprints, protection metadata, and optionally "
                    "content for one explicitly registered local memory source. Arbitrary paths "
                    "are never accepted."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "minLength": 1},
                        "include_content": {"type": "boolean", "default": False},
                    },
                    "required": ["source_id"],
                    "additionalProperties": False,
                },
                handler=self._inspect_memory,
                read_only=True,
                idempotent=True,
            ),
            McpTool(
                name="prepare_memory_suggestions",
                title="Prepare memory review",
                description=(
                    "Bind LLM keep/delete/replace/protect suggestions to current local segment "
                    "fingerprints and persist an immutable human review request. No file is edited."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "minLength": 1},
                        "suggestions": {"type": "array", "items": memory_item},
                    },
                    "required": ["source_id", "suggestions"],
                    "additionalProperties": False,
                },
                handler=self._prepare_memory,
                read_only=False,
                idempotent=False,
            ),
            McpTool(
                name="open_memory_review",
                title="Open memory review",
                description=(
                    "Validate a sealed memory request, queue it, and open the original local GUI. "
                    "No memory file is edited by this tool."
                ),
                input_schema=request_id_schema,
                handler=self._open_memory,
                read_only=False,
                idempotent=True,
            ),
            McpTool(
                name="get_pending_review_status",
                title="Get review status",
                description="Report whether an immutable review request is queued or accepted.",
                input_schema=request_id_schema,
                handler=self._review_status,
                read_only=True,
                idempotent=True,
            ),
            McpTool(
                name="open_review_demo",
                title="Open read-only review demo",
                description=(
                    "Create and open a synthetic cleanup review request. It does not inspect or "
                    "modify Codex conversations."
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=self._open_demo,
                read_only=False,
                idempotent=False,
            ),
        )

    def handle_payload(self, payload: Any) -> Any:
        if isinstance(payload, list):
            if not payload:
                return self._error(None, -32600, "Invalid Request")
            responses = [self.handle_message(message) for message in payload]
            filtered = [response for response in responses if response is not None]
            return filtered or None
        return self.handle_message(payload)

    def handle_message(self, message: Any) -> JsonObject | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return self._error(request_id, -32600, "Invalid Request")
        notification = "id" not in message
        try:
            result = self._dispatch(method, params)
        except MethodNotFoundError as exc:
            if notification:
                return None
            return self._error(request_id, -32601, str(exc))
        except (TypeError, ValueError) as exc:
            if notification:
                return None
            return self._error(request_id, -32602, str(exc))
        except OSError as exc:
            if notification:
                return None
            return self._error(request_id, -32000, str(exc))
        if notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: JsonObject) -> Any:
        if method == "initialize":
            requested = params.get("protocolVersion")
            protocol = (
                requested
                if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS
                else DEFAULT_PROTOCOL_VERSION
            )
            return {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "codex-session-manager",
                    "title": "CodexSessionManager",
                    "version": __version__,
                },
                "instructions": (
                    "Tools only inspect metadata, prepare immutable suggestions, query status, "
                    "or open the local human-review GUI. Never claim a tool archived, trimmed, "
                    "deleted, restored, or edited memory."
                ),
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.descriptor() for tool in self.tools.values()]}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("tools/call requires a tool name and object arguments")
            return self._call_tool(name, arguments)
        raise MethodNotFoundError(f"method not found: {method}")

    def _call_tool(self, name: str, arguments: JsonObject) -> JsonObject:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"unknown tool: {name}")
        try:
            value = _jsonable(tool.handler(arguments))
        except (OSError, TypeError, ValueError) as exc:
            text = json.dumps(
                {"error": str(exc), "tool": name},
                ensure_ascii=False,
                sort_keys=True,
            )
            return {"content": [{"type": "text", "text": text}], "isError": True}
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": value,
            "isError": False,
        }

    def _inspect_inventory(self, arguments: JsonObject) -> Any:
        days = int(arguments.get("older_than_days", 90))
        return inspect_conversation_inventory(paths=self.paths, older_than_days=days)

    def _prepare_cleanup(self, arguments: JsonObject) -> Any:
        days = int(arguments.get("older_than_days", 90))
        raw = arguments.get("suggestions")
        if not isinstance(raw, list):
            raise ValueError("suggestions must be an array")
        suggestions = tuple(CleanupSuggestionInput.model_validate(item) for item in raw)
        result = prepare_cleanup_suggestions_from_current(
            paths=self.paths,
            older_than_days=days,
            llm_suggestions=suggestions,
        )
        return {"prepared": result is not None, "review": _jsonable(result)}

    def _prepare_context(self, arguments: JsonObject) -> Any:
        thread_id = arguments.get("thread_id")
        raw = arguments.get("suggestions")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        if not isinstance(raw, list):
            raise ValueError("suggestions must be an array")
        suggestions = tuple(ContextSuggestionInput.model_validate(item) for item in raw)
        return prepare_context_suggestions_from_current(
            paths=self.paths,
            thread_id=thread_id,
            llm_suggestions=suggestions,
        )

    def _inspect_memory(self, arguments: JsonObject) -> Any:
        source_id = arguments.get("source_id")
        include_content = arguments.get("include_content", False)
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(include_content, bool):
            raise ValueError("include_content must be a boolean")
        return inspect_memory_source(
            source_id,
            paths=self.paths,
            include_content=include_content,
        )

    def _prepare_memory(self, arguments: JsonObject) -> Any:
        source_id = arguments.get("source_id")
        raw = arguments.get("suggestions")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(raw, list):
            raise ValueError("suggestions must be an array")
        suggestions = tuple(MemorySuggestionInput.model_validate(item) for item in raw)
        return prepare_memory_review(
            source_id,
            suggestions,
            paths=self.paths,
        )

    def _open_cleanup(self, arguments: JsonObject) -> Any:
        return open_sealed_review(
            self._request_id(arguments),
            expected_operation=ReviewOperation.CONVERSATION_CLEANUP,
            paths=self.paths,
            launcher=self.launcher,
        )

    def _open_context(self, arguments: JsonObject) -> Any:
        return open_sealed_review(
            self._request_id(arguments),
            expected_operation=ReviewOperation.CONTEXT_TRIM,
            paths=self.paths,
            launcher=self.launcher,
        )

    def _open_memory(self, arguments: JsonObject) -> Any:
        return open_sealed_review(
            self._request_id(arguments),
            expected_operation=ReviewOperation.MEMORY_EDIT,
            paths=self.paths,
            launcher=self.launcher,
        )

    def _review_status(self, arguments: JsonObject) -> Any:
        return get_pending_review_status(self._request_id(arguments), paths=self.paths)

    def _open_demo(self, arguments: JsonObject) -> Any:
        if arguments:
            raise ValueError("open_review_demo does not accept arguments")
        return open_review_demo(paths=self.paths, launcher=self.launcher)

    @staticmethod
    def _request_id(arguments: JsonObject) -> str:
        value = arguments.get("request_id")
        if not isinstance(value, str) or not value:
            raise ValueError("request_id must be a non-empty string")
        return value

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> JsonObject:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


@dataclass(frozen=True, slots=True)
class McpHttpConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    endpoint_path: str = "/mcp"
    bearer_token: str | None = None
    allowed_origins: tuple[str, ...] = ()
    allow_unauthenticated_local: bool = False
    max_request_bytes: int = MAX_REQUEST_BYTES

    def validate(self) -> None:
        if not self.endpoint_path.startswith("/") or "?" in self.endpoint_path:
            raise ValueError("MCP endpoint path must be an absolute path without a query")
        if not 1 <= self.port <= 65535:
            raise ValueError("MCP port must be between 1 and 65535")
        if self.max_request_bytes < 1:
            raise ValueError("MCP request-size limit must be positive")
        for origin in self.allowed_origins:
            if origin == "*" or not origin.startswith(("https://", "http://")):
                raise ValueError("allowed MCP origins must be exact http(s) origins, not wildcards")
        if self.bearer_token is not None:
            if not self.bearer_token:
                raise ValueError("MCP bearer token must not be empty")
            return
        if not self.allow_unauthenticated_local:
            raise ValueError(
                "CSM MCP requires a bearer token unless unauthenticated local mode is explicitly enabled"
            )
        try:
            if not ipaddress.ip_address(self.host).is_loopback:
                raise ValueError("unauthenticated MCP mode may bind only to a loopback address")
        except ValueError as exc:
            raise ValueError(
                "unauthenticated MCP mode requires an explicit loopback IP such as 127.0.0.1"
            ) from exc


def mcp_http_config_from_environment() -> McpHttpConfig:
    """Build the opt-in desktop auto-start MCP configuration from the environment."""

    raw_origins = os.environ.get("CSM_MCP_ALLOWED_ORIGINS", "https://chatgpt.com")
    allowed_origins = tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
    return McpHttpConfig(
        host="127.0.0.1",
        port=int(os.environ.get("CSM_MCP_PORT", "8765")),
        endpoint_path=os.environ.get("CSM_MCP_PATH", "/mcp"),
        bearer_token=os.environ.get("CSM_MCP_BEARER_TOKEN"),
        allowed_origins=allowed_origins,
        allow_unauthenticated_local=os.environ.get("CSM_MCP_ALLOW_UNAUTHENTICATED_LOCAL") == "1",
    )


class McpServerLifecycle:
    """Own one opt-in in-process MCP HTTP server for the desktop lifetime."""

    def __init__(
        self,
        *,
        config: McpHttpConfig,
        application: McpApplication | None = None,
    ) -> None:
        self._config = config
        self._application = application
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("MCP server lifecycle is already running")
        server = create_mcp_http_server(config=self._config, application=self._application)
        thread = threading.Thread(
            target=server.serve_forever,
            name="CodexSessionManager-MCP",
            daemon=True,
        )
        try:
            thread.start()
        except BaseException:
            server.server_close()
            raise
        self._server = server
        self._thread = thread

    def close(self) -> None:
        server = self._server
        thread = self._thread
        if server is None or thread is None:
            return
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        self._server = None
        self._thread = None


def start_mcp_from_environment(*, paths: AppPaths) -> McpServerLifecycle | None:
    """Start MCP only when the desktop launcher explicitly opts in."""

    if os.environ.get("CSM_MCP_AUTO_START") != "1":
        return None
    lifecycle = McpServerLifecycle(
        config=mcp_http_config_from_environment(),
        application=McpApplication(paths=paths),
    )
    lifecycle.start()
    return lifecycle


def serve_mcp_stdio(
    *,
    application: McpApplication | None = None,
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> None:
    """Serve MCP over newline-delimited JSON for a local Codex client.

    Codex starts and owns this process from its local MCP configuration.  The
    transport deliberately writes only JSON-RPC responses to stdout; any
    diagnostics must be emitted by the caller to stderr.
    """

    app = application or McpApplication()
    input_buffer = input_stream or sys.stdin.buffer
    output_buffer = output_stream or sys.stdout.buffer
    for raw_line in input_buffer:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response: Any = McpApplication._error(None, -32700, "Parse error")
        else:
            response = app.handle_payload(payload)
        if response is None:
            continue
        data = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        output_buffer.write(data + b"\n")
        output_buffer.flush()


class _McpHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        application: McpApplication,
        config: McpHttpConfig,
    ) -> None:
        self.mcp_application = application
        self.mcp_config = config
        super().__init__(address, _McpRequestHandler)


class _McpRequestHandler(BaseHTTPRequestHandler):
    server_version = "CodexSessionManager-MCP"
    sys_version = ""

    @property
    def mcp_server(self) -> _McpHttpServer:
        return cast(_McpHttpServer, self.server)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "csm-mcp"})
            return
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "POST is required")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        config = self.mcp_server.mcp_config
        if self.path != config.endpoint_path:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self._origin_allowed(config):
            self.send_error(HTTPStatus.FORBIDDEN, "Origin is not allowed")
            return
        if not self._authorized(config):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Bearer realm="CodexSessionManager MCP"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        content_type = self.headers.get("Content-Type", "").partition(";")[0].strip()
        if content_type != "application/json":
            self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "application/json is required")
            return
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if length < 1 or length > config.max_request_bytes:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                McpApplication._error(None, -32700, "Parse error"),
            )
            return
        response = self.mcp_server.mcp_application.handle_payload(payload)
        if response is None:
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(HTTPStatus.OK, response)

    def _authorized(self, config: McpHttpConfig) -> bool:
        if config.bearer_token is not None:
            authorization = self.headers.get("Authorization", "")
            scheme, separator, value = authorization.partition(" ")
            return (
                bool(separator)
                and scheme.casefold() == "bearer"
                and secrets.compare_digest(value, config.bearer_token)
            )
        if not config.allow_unauthenticated_local:
            return False
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _origin_allowed(self, config: McpHttpConfig) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in config.allowed_origins

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("MCP-Protocol-Version", DEFAULT_PROTOCOL_VERSION)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log authorization headers, tool arguments, or response bodies.
        return


def create_mcp_http_server(
    *,
    config: McpHttpConfig,
    application: McpApplication | None = None,
) -> ThreadingHTTPServer:
    config.validate()
    app = application or McpApplication()
    return _McpHttpServer((config.host, config.port), app, config)


def serve_mcp_http(
    *,
    config: McpHttpConfig,
    application: McpApplication | None = None,
) -> None:
    """Serve the stateless MCP endpoint until interrupted."""

    server = create_mcp_http_server(config=config, application=application)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
