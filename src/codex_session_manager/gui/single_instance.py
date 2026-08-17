"""Single-instance desktop coordination over a bounded local Qt channel."""

from __future__ import annotations

import contextlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from PySide6.QtCore import QIODevice, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from codex_session_manager.config import AppPaths
from codex_session_manager.hashing import canonical_json_bytes, fingerprint

_MAX_MESSAGE_BYTES = 64 * 1024
_SAFE_COMMAND_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_MAX_UNIX_SOCKET_PATH_BYTES = 100


class DesktopCommandKind(StrEnum):
    ACTIVATE = "activate"
    OPEN_THREAD = "open_thread"
    OPEN_REVIEW_REQUEST = "open_review_request"


class DesktopCommand(BaseModel):
    """Strict local command accepted by the primary desktop process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    command_id: str = Field(pattern=_SAFE_COMMAND_ID_PATTERN)
    kind: DesktopCommandKind
    thread_id: str | None = None
    pending_request_path: str | None = None

    @classmethod
    def activate(cls) -> Self:
        return cls(command_id=str(uuid4()), kind=DesktopCommandKind.ACTIVATE)

    @classmethod
    def open_thread(cls, thread_id: str) -> Self:
        return cls(
            command_id=str(uuid4()),
            kind=DesktopCommandKind.OPEN_THREAD,
            thread_id=thread_id,
        )

    @classmethod
    def open_review_request(cls, pending_request_path: Path) -> Self:
        return cls(
            command_id=str(uuid4()),
            kind=DesktopCommandKind.OPEN_REVIEW_REQUEST,
            pending_request_path=str(pending_request_path),
        )

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.kind is DesktopCommandKind.ACTIVATE:
            if self.thread_id is not None or self.pending_request_path is not None:
                raise ValueError("activate command does not accept a target")
        elif self.kind is DesktopCommandKind.OPEN_THREAD:
            if not self.thread_id or self.pending_request_path is not None:
                raise ValueError("open_thread requires exactly one thread id")
        elif self.kind is DesktopCommandKind.OPEN_REVIEW_REQUEST and (
            not self.pending_request_path or self.thread_id is not None
        ):
            raise ValueError("open_review_request requires exactly one queue path")
        return self


class DesktopResponse(BaseModel):
    """Bounded acknowledgement returned by the primary desktop process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    command_id: str = Field(pattern=_SAFE_COMMAND_ID_PATTERN)
    accepted: bool
    message: str = ""


class InstanceRole(StrEnum):
    PRIMARY = "primary"
    FORWARDED = "forwarded"


def server_name(paths: AppPaths) -> str:
    """Return a stable, non-secret logical name scoped to one CSM data root."""

    root_digest = fingerprint({"data_dir": str(paths.data_dir.resolve(strict=False))})[:32]
    return f"CodexSessionManager-{root_digest}"


def _user_socket_directory() -> Path:
    """Create a short, current-user-only directory for Unix domain sockets."""

    if not hasattr(os, "getuid"):
        raise OSError("当前平台无法解析 Unix 用户 ID")
    user_id = os.getuid()
    directory = Path("/tmp") / f"codex-session-manager-{user_id}"
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OSError(f"桌面 IPC 目录不是可信目录：{directory}")
    if metadata.st_uid != user_id:
        raise OSError(f"桌面 IPC 目录属于其他用户：{directory}")
    directory.chmod(0o700)
    return directory


def server_endpoint(
    paths: AppPaths,
    *,
    logical_name: str | None = None,
    platform: str = sys.platform,
) -> str:
    """Return a platform endpoint that stays below Unix socket path limits."""

    name = logical_name or server_name(paths)
    if platform == "win32":
        return name
    if platform == "darwin" or platform.startswith("linux"):
        endpoint_digest = fingerprint({"logical_name": name})[:32]
        endpoint = _user_socket_directory() / f"ipc-{endpoint_digest}.sock"
        if len(os.fsencode(endpoint)) >= _MAX_UNIX_SOCKET_PATH_BYTES:
            raise OSError(f"桌面 IPC 路径过长：{endpoint}")
        return str(endpoint)
    return name


def _response_for_exception(command_id: str, exc: Exception) -> DesktopResponse:
    return DesktopResponse(command_id=command_id, accepted=False, message=str(exc))


class SingleInstanceBroker(QObject):
    """Own the primary local server or forward one command to an existing owner."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        name: str | None = None,
        platform: str = sys.platform,
    ) -> None:
        super().__init__()
        self.logical_name = name or server_name(paths)
        self.name = server_endpoint(
            paths,
            logical_name=self.logical_name,
            platform=platform,
        )
        self.server = QLocalServer(self)
        # Qt documents socket access flags as effective on Linux and Windows.
        # macOS ignores them, and forcing the option can switch a short logical
        # name to an overlong filesystem socket path in sandboxed environments.
        if platform.startswith("linux") or platform == "win32":
            self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._handler: Callable[[DesktopCommand], DesktopResponse] | None = None
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._owns_server = False
        self.server.newConnection.connect(self._accept_connections)

    def acquire_or_forward(
        self,
        command: DesktopCommand,
        handler: Callable[[DesktopCommand], DesktopResponse],
    ) -> tuple[InstanceRole, DesktopResponse | None]:
        """Become primary, or synchronously deliver the command to the primary."""

        if self.server.listen(self.name):
            self._handler = handler
            self._owns_server = True
            return InstanceRole.PRIMARY, None

        response = self._forward(command)
        if response is not None:
            return InstanceRole.FORWARDED, response

        # A process may be between binding the endpoint and entering its event
        # loop. Probe briefly before treating the endpoint as stale.
        for _attempt in range(3):
            time.sleep(0.05)
            response = self._forward(command)
            if response is not None:
                return InstanceRole.FORWARDED, response

        QLocalServer.removeServer(self.name)
        if self.server.listen(self.name):
            self._handler = handler
            self._owns_server = True
            return InstanceRole.PRIMARY, None

        response = self._forward(command)
        if response is not None:
            return InstanceRole.FORWARDED, response
        raise OSError(f"无法取得桌面单实例端点：{self.server.errorString()}")

    def close(self) -> None:
        if self._owns_server:
            self.server.close()
            QLocalServer.removeServer(self.name)
            self._owns_server = False

    def _forward(self, command: DesktopCommand) -> DesktopResponse | None:
        socket = QLocalSocket()
        socket.connectToServer(self.name, QIODevice.OpenModeFlag.ReadWrite)
        if not socket.waitForConnected(250):
            socket.abort()
            return None

        payload = canonical_json_bytes(command) + b"\n"
        if socket.write(payload) != len(payload):
            socket.abort()
            return None
        socket.flush()
        if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(1000):
            socket.abort()
            return None
        if socket.bytesAvailable() == 0:
            socket.waitForReadyRead(2000)
        if socket.bytesAvailable() == 0:
            socket.abort()
            return None

        response_bytes = bytearray()
        while socket.bytesAvailable() or socket.waitForReadyRead(50):
            response_bytes.extend(socket.readAll().data())
            if b"\n" in response_bytes or len(response_bytes) > _MAX_MESSAGE_BYTES:
                break
        socket.disconnectFromServer()
        line, separator, _remainder = response_bytes.partition(b"\n")
        if not separator or len(line) > _MAX_MESSAGE_BYTES:
            return None
        try:
            response = DesktopResponse.model_validate_json(line)
        except ValueError:
            return None
        return response if response.command_id == command.command_id else None

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                return
            socket.setParent(self)
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read_socket(socket))
            socket.disconnected.connect(lambda socket=socket: self._drop_socket(socket))
            if socket.bytesAvailable() > 0:
                self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(socket.readAll().data())
        if len(buffer) > _MAX_MESSAGE_BYTES:
            self._write_response(
                socket,
                DesktopResponse(
                    command_id=str(uuid4()),
                    accepted=False,
                    message="桌面命令超过大小限制",
                ),
            )
            return
        line, separator, _remainder = buffer.partition(b"\n")
        if not separator:
            return
        self._buffers.pop(socket, None)

        try:
            command = DesktopCommand.model_validate_json(line)
        except ValueError as exc:
            response = _response_for_exception(str(uuid4()), exc)
        else:
            handler = self._handler
            if handler is None:
                response = DesktopResponse(
                    command_id=command.command_id,
                    accepted=False,
                    message="桌面主进程尚未准备好",
                )
            else:
                try:
                    response = handler(command)
                except Exception as exc:
                    response = _response_for_exception(command.command_id, exc)
            if response.command_id != command.command_id:
                response = DesktopResponse(
                    command_id=command.command_id,
                    accepted=False,
                    message="桌面主进程返回了不匹配的命令确认",
                )
        self._write_response(socket, response)

    def _write_response(self, socket: QLocalSocket, response: DesktopResponse) -> None:
        payload = (
            json.dumps(
                response.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        if socket.write(payload) != len(payload):
            socket.abort()
            return
        socket.flush()
        socket.disconnectFromServer()

    def _drop_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        with contextlib.suppress(RuntimeError):
            socket.deleteLater()
