from __future__ import annotations

import http.client
import io
import json
import socket
from pathlib import Path

import pytest

from codex_session_manager.mcp_server import (
    DEFAULT_PROTOCOL_VERSION,
    McpApplication,
    McpHttpConfig,
    McpServerLifecycle,
    mcp_http_config_from_environment,
    serve_mcp_stdio,
)
from codex_session_manager.memory import MemorySourceRegistry
from codex_session_manager.review_requests import ReviewRequestQueue, ReviewRequestStore


def _request(message_id: int, method: str, params: dict[str, object] | None = None):
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": method,
        "params": params or {},
    }


def test_mcp_initialization_and_tool_surface_are_bounded(app_paths) -> None:
    application = McpApplication(paths=app_paths, launcher=lambda _path: None)

    initialized = application.handle_message(
        _request(
            1,
            "initialize",
            {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
    )
    listed = application.handle_message(_request(2, "tools/list"))

    assert initialized is not None
    assert initialized["result"]["protocolVersion"] == DEFAULT_PROTOCOL_VERSION
    assert initialized["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert listed is not None
    tools = listed["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "inspect_conversation_inventory",
        "prepare_cleanup_suggestions",
        "open_cleanup_review",
        "prepare_context_suggestions",
        "open_context_review",
        "inspect_memory_source",
        "prepare_memory_suggestions",
        "open_memory_review",
        "get_pending_review_status",
        "open_review_demo",
    }
    assert not any(
        token in name
        for name in names
        for token in ("delete", "purge", "execute", "apply_memory", "apply_trim")
    )
    annotations = {tool["name"]: tool["annotations"] for tool in tools}
    assert annotations["inspect_conversation_inventory"]["readOnlyHint"] is True
    assert annotations["inspect_memory_source"]["readOnlyHint"] is True
    assert annotations["get_pending_review_status"]["readOnlyHint"] is True
    assert all(value["destructiveHint"] is False for value in annotations.values())


def test_mcp_memory_suggestions_bind_registered_segments_and_open_original_gui(
    tmp_path, app_paths
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("# Profile\n\nLikes tea.\n", encoding="utf-8")
    source = MemorySourceRegistry(app_paths).register(file_path=target, root_path=root)
    launched: list[Path] = []
    application = McpApplication(paths=app_paths, launcher=launched.append)

    inspected = application.handle_message(
        _request(
            1,
            "tools/call",
            {
                "name": "inspect_memory_source",
                "arguments": {"source_id": source.source_id, "include_content": True},
            },
        )
    )
    assert inspected is not None
    payload = inspected["result"]["structuredContent"]
    paragraph = next(item for item in payload["segments"] if "Likes tea" in item["text"])

    prepared = application.handle_message(
        _request(
            2,
            "tools/call",
            {
                "name": "prepare_memory_suggestions",
                "arguments": {
                    "source_id": source.source_id,
                    "suggestions": [
                        {
                            "target_id": paragraph["target_id"],
                            "suggested_action": "replace",
                            "suggested_text": "Likes green tea.",
                            "reason": "用户偏好已更新",
                            "confidence": 0.9,
                        }
                    ],
                },
            },
        )
    )
    assert prepared is not None
    review = prepared["result"]["structuredContent"]
    request = ReviewRequestStore(app_paths).load(Path(review["request_path"]))
    assert request.target_paths == (str(target),)

    opened = application.handle_message(
        _request(
            3,
            "tools/call",
            {
                "name": "open_memory_review",
                "arguments": {"request_id": request.request_id},
            },
        )
    )
    assert opened is not None
    assert opened["result"]["structuredContent"]["launched"] is True
    assert launched == [Path(review["request_path"])]


def test_mcp_demo_open_and_status_use_immutable_local_queue(app_paths) -> None:
    launched: list[Path] = []
    application = McpApplication(paths=app_paths, launcher=launched.append)

    opened = application.handle_message(
        _request(
            1,
            "tools/call",
            {"name": "open_review_demo", "arguments": {}},
        )
    )

    assert opened is not None
    tool_result = opened["result"]
    assert tool_result["isError"] is False
    structured = tool_result["structuredContent"]
    assert structured["launched"] is True
    assert launched == [Path(structured["request_path"])]
    request_id = structured["request_id"]

    queued = application.handle_message(
        _request(
            2,
            "tools/call",
            {
                "name": "get_pending_review_status",
                "arguments": {"request_id": request_id},
            },
        )
    )
    assert queued is not None
    assert queued["result"]["structuredContent"]["status"] == "queued"

    request_path = app_paths.review_requests_dir / f"review-{request_id}.json"
    request = ReviewRequestStore(app_paths).load(request_path)
    ReviewRequestQueue(app_paths).acknowledge(request)
    accepted = application.handle_message(
        _request(
            3,
            "tools/call",
            {
                "name": "get_pending_review_status",
                "arguments": {"request_id": request_id},
            },
        )
    )
    assert accepted is not None
    assert accepted["result"]["structuredContent"]["status"] == "accepted"


def test_mcp_invalid_tool_arguments_are_returned_as_tool_errors(app_paths) -> None:
    application = McpApplication(paths=app_paths, launcher=lambda _path: None)

    response = application.handle_message(
        _request(
            1,
            "tools/call",
            {
                "name": "get_pending_review_status",
                "arguments": {"request_id": "../escape"},
            },
        )
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["tool"] == "get_pending_review_status"
    assert "unsafe" in payload["error"]


def test_mcp_json_rpc_method_and_notification_semantics(app_paths) -> None:
    application = McpApplication(paths=app_paths, launcher=lambda _path: None)

    missing = application.handle_message(_request(1, "resources/list"))
    notification = application.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    )

    assert missing is not None
    assert missing["error"]["code"] == -32601
    assert notification is None


def test_mcp_http_config_requires_explicit_auth_boundary() -> None:
    with pytest.raises(ValueError, match="bearer token"):
        McpHttpConfig().validate()

    local = McpHttpConfig(allow_unauthenticated_local=True)
    local.validate()

    with pytest.raises(ValueError, match="loopback"):
        McpHttpConfig(
            host="0.0.0.0",
            allow_unauthenticated_local=True,
        ).validate()

    with pytest.raises(ValueError, match="must not be empty"):
        McpHttpConfig(bearer_token="").validate()

    with pytest.raises(ValueError, match="not wildcards"):
        McpHttpConfig(
            bearer_token="secret",
            allowed_origins=("*",),
        ).validate()

    protected = McpHttpConfig(
        host="0.0.0.0",
        bearer_token="secret",
        allowed_origins=("https://chatgpt.com",),
    )
    protected.validate()


def test_mcp_http_config_from_environment_is_loopback_and_chatgpt_scoped(monkeypatch) -> None:
    monkeypatch.setenv("CSM_MCP_PORT", "9876")
    monkeypatch.setenv("CSM_MCP_PATH", "/test-mcp")
    monkeypatch.setenv(
        "CSM_MCP_ALLOWED_ORIGINS",
        "https://chatgpt.com, https://chat.openai.com",
    )
    monkeypatch.setenv("CSM_MCP_BEARER_TOKEN", "test-only-token")

    config = mcp_http_config_from_environment()

    assert config.host == "127.0.0.1"
    assert config.port == 9876
    assert config.endpoint_path == "/test-mcp"
    assert config.allowed_origins == (
        "https://chatgpt.com",
        "https://chat.openai.com",
    )
    assert config.bearer_token == "test-only-token"
    assert config.allow_unauthenticated_local is False


def test_mcp_server_lifecycle_starts_and_stops_with_desktop(app_paths) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    lifecycle = McpServerLifecycle(
        config=McpHttpConfig(
            port=port,
            bearer_token="test-only-token",
            allowed_origins=("https://chatgpt.com",),
        ),
        application=McpApplication(paths=app_paths, launcher=lambda _path: None),
    )
    lifecycle.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert response.status == 200
        connection.close()
    finally:
        lifecycle.close()


def test_mcp_http_transport_enforces_auth_origin_size_and_tool_surface(app_paths) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    lifecycle = McpServerLifecycle(
        config=McpHttpConfig(
            port=port,
            bearer_token="test-only-token",
            allowed_origins=("https://chatgpt.com",),
            max_request_bytes=128,
        ),
        application=McpApplication(paths=app_paths, launcher=lambda _path: None),
    )
    lifecycle.start()

    def request(
        path: str,
        *,
        body: bytes = b"{}",
        token: str | None = "test-only-token",
        origin: str | None = "https://chatgpt.com",
        content_type: str = "application/json",
    ) -> tuple[int, bytes]:
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if origin is not None:
            headers["Origin"] = origin
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        result = (response.status, response.read())
        connection.close()
        return result

    try:
        assert request("/mcp", token=None)[0] == 401
        assert request("/mcp", origin="https://not-chatgpt.example")[0] == 403
        assert request("/mcp", content_type="text/plain")[0] == 415
        assert request("/mcp", body=b"x" * 129)[0] == 413
        assert request("/not-mcp")[0] == 404

        status, body = request(
            "/mcp",
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            ).encode(),
        )
        assert status == 200
        names = {item["name"] for item in json.loads(body)["result"]["tools"]}
        assert names == {
            "inspect_conversation_inventory",
            "prepare_cleanup_suggestions",
            "open_cleanup_review",
            "prepare_context_suggestions",
            "open_context_review",
            "inspect_memory_source",
            "prepare_memory_suggestions",
            "open_memory_review",
            "get_pending_review_status",
            "open_review_demo",
        }
    finally:
        lifecycle.close()


def test_mcp_stdio_transport_returns_json_rpc_and_skips_notifications(app_paths) -> None:
    input_stream = io.BytesIO(
        b"\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": DEFAULT_PROTOCOL_VERSION},
                    }
                ).encode(),
                json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
                ).encode(),
                json.dumps(
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                ).encode(),
                b"not-json",
            ]
        )
        + b"\n"
    )
    output_stream = io.BytesIO()

    serve_mcp_stdio(
        application=McpApplication(paths=app_paths, launcher=lambda _path: None),
        input_stream=input_stream,
        output_stream=output_stream,
    )

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert [response["id"] for response in responses] == [1, 2, None]
    assert responses[0]["result"]["serverInfo"]["version"] == "1.1.0"
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {
        "inspect_conversation_inventory",
        "prepare_cleanup_suggestions",
        "open_cleanup_review",
        "prepare_context_suggestions",
        "open_context_review",
        "inspect_memory_source",
        "prepare_memory_suggestions",
        "open_memory_review",
        "get_pending_review_status",
        "open_review_demo",
    }
    assert responses[2]["error"]["code"] == -32700
