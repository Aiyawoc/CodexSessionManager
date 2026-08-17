from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from uuid import uuid4

import pytest
from pydantic import ValidationError
from PySide6.QtNetwork import QLocalServer

from codex_session_manager.gui.controller import TrimReviewWindow
from codex_session_manager.gui.main import DesktopWindowManager
from codex_session_manager.gui.main_window import UnifiedMainWindow
from codex_session_manager.gui.review_mode import ReviewMode
from codex_session_manager.gui.single_instance import (
    DesktopCommand,
    DesktopCommandKind,
    DesktopPage,
    DesktopResponse,
    InstanceRole,
    SingleInstanceBroker,
    _command_payload,
)
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewRequestQueue,
    ReviewRequestStore,
    ReviewSource,
    codex_account_fingerprint,
)


def test_desktop_command_rejects_mixed_targets() -> None:
    with pytest.raises(ValidationError, match="does not accept a target"):
        DesktopCommand(
            command_id="command-1",
            kind=DesktopCommandKind.ACTIVATE,
            thread_id="thread-1",
        )

    with pytest.raises(ValidationError, match="requires exactly one queue path"):
        DesktopCommand(
            command_id="command-2",
            kind=DesktopCommandKind.OPEN_REVIEW_REQUEST,
        )

    with pytest.raises(ValidationError, match="requires exactly one page"):
        DesktopCommand(
            command_id="command-3",
            kind=DesktopCommandKind.OPEN_PAGE,
        )

    command = DesktopCommand.open_page(DesktopPage.PENDING)
    assert command.kind is DesktopCommandKind.OPEN_PAGE
    assert command.page is DesktopPage.PENDING


def test_desktop_command_omits_new_absent_fields_for_rolling_upgrades() -> None:
    command = DesktopCommand.activate()

    payload = json.loads(_command_payload(command))

    assert payload == {
        "schema_version": 1,
        "command_id": command.command_id,
        "kind": DesktopCommandKind.ACTIVATE.value,
    }


def test_single_instance_endpoint_and_access_follow_platform(app_paths) -> None:
    broker = SingleInstanceBroker(app_paths, name="csm-platform-test")

    expected_options = (
        QLocalServer.SocketOption.UserAccessOption
        if sys.platform.startswith("linux") or sys.platform == "win32"
        else QLocalServer.SocketOption.NoOptions
    )
    assert broker.server.socketOptions() == expected_options
    if sys.platform != "win32":
        endpoint = os.fsencode(broker.name)
        directory = os.path.dirname(broker.name)
        assert len(endpoint) < 100
        assert os.stat(directory).st_uid == os.getuid()
        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700


def test_window_manager_opens_each_review_request_once(qtbot, app_paths, monkeypatch) -> None:
    monkeypatch.setattr(TrimReviewWindow, "load_task_list", lambda _self: None)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=("thread-1",),
    )
    request_path = ReviewRequestStore(app_paths).save(request)
    queue = ReviewRequestQueue(app_paths)
    _request, pending_path = queue.enqueue(request_path)
    manager = DesktopWindowManager(app_paths)

    response = manager.handle_command(DesktopCommand.open_review_request(pending_path))

    assert response.accepted
    assert not pending_path.exists()
    assert len(manager._windows) == 1
    window = next(iter(manager._windows.values()))
    qtbot.addWidget(window)
    assert isinstance(window, TrimReviewWindow)
    assert window.property("csmReviewRequestId") == request.request_id
    assert window.property("csmReviewOperation") == request.operation.value
    assert window.review_mode is ReviewMode.CONVERSATION_CLEANUP
    assert window.windowTitle() == "CodexSessionManager · 对话清理审查"
    assert window.ui.taskDeleteButton.isHidden()

    _request, pending_path = queue.enqueue(request_path)
    second = manager.handle_command(DesktopCommand.open_review_request(pending_path))

    assert second.accepted
    assert not pending_path.exists()
    assert len(manager._windows) == 1
    assert next(iter(manager._windows.values())) is window
    window.close()


def test_window_manager_reuses_original_gui_for_review_modes(qtbot, app_paths, monkeypatch) -> None:
    monkeypatch.setattr(TrimReviewWindow, "load_task_list", lambda _self: None)
    manager = DesktopWindowManager(app_paths)

    first = manager.handle_command(DesktopCommand.open_page(DesktopPage.CLEANUP))
    second = manager.handle_command(DesktopCommand.open_page(DesktopPage.MEMORY))
    third = manager.handle_command(DesktopCommand.open_page(DesktopPage.PENDING))

    assert first.accepted
    assert second.accepted
    assert third.accepted
    assert set(manager._windows) == {"review-shell", "workspace"}
    review_window = manager._windows["review-shell"]
    workspace = manager._windows["workspace"]
    qtbot.addWidget(review_window)
    qtbot.addWidget(workspace)
    assert isinstance(review_window, TrimReviewWindow)
    assert review_window.review_mode is ReviewMode.MEMORY_EDIT
    assert isinstance(workspace, UnifiedMainWindow)
    assert workspace.current_page is DesktopPage.PENDING
    review_window.close()
    workspace.close()


def test_single_instance_forwards_command_to_primary(qtbot, app_paths) -> None:
    name = f"csm-test-{uuid4()}"
    primary = SingleInstanceBroker(app_paths, name=name)
    received: list[DesktopCommand] = []

    def handle(command: DesktopCommand) -> DesktopResponse:
        received.append(command)
        return DesktopResponse(
            command_id=command.command_id,
            accepted=True,
            message="accepted",
        )

    role, response = primary.acquire_or_forward(DesktopCommand.activate(), handle)
    assert role is InstanceRole.PRIMARY
    assert response is None

    client_code = textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path

        from codex_session_manager.config import AppPaths
        from codex_session_manager.gui.single_instance import (
            DesktopCommand,
            DesktopResponse,
            SingleInstanceBroker,
        )

        root = Path.cwd()
        data = root / ".test-single-instance-client"
        paths = AppPaths(
            data_dir=data,
            config_dir=data / "config",
            cache_dir=data / "cache",
            log_dir=data / "log",
            plans_dir=data / "plans",
            imports_dir=data / "imports",
            backups_dir=data / "backups",
            audit_db=data / "audit.sqlite3",
            codex_home=data / "codex-home",
        )
        broker = SingleInstanceBroker(paths, name=sys.argv[1])

        def unexpected_primary(command):
            return DesktopResponse(
                command_id=command.command_id,
                accepted=False,
                message="secondary unexpectedly became primary",
            )

        role, response = broker.acquire_or_forward(
            DesktopCommand.open_thread("thread-1"),
            unexpected_primary,
        )
        print(json.dumps({
            "role": role.value,
            "accepted": response.accepted if response is not None else None,
            "message": response.message if response is not None else "",
        }))
        broker.close()
        """
    )
    repository = os.fspath(os.path.dirname(os.path.dirname(__file__)))
    process = subprocess.Popen(
        [sys.executable, "-c", client_code, name],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
        stdout, stderr = process.communicate(timeout=1)

        assert process.returncode == 0, stderr
        forwarded = json.loads(stdout)
        assert forwarded == {
            "role": InstanceRole.FORWARDED.value,
            "accepted": True,
            "message": "accepted",
        }
        assert [command.thread_id for command in received] == ["thread-1"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        primary.close()
