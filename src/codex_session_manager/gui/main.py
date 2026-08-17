"""Standalone GUI entry point."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer

from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.gui.application import ensure_application
from codex_session_manager.gui.controller import TrimReviewWindow
from codex_session_manager.gui.main_window import UnifiedMainWindow
from codex_session_manager.gui.review_mode import ReviewMode
from codex_session_manager.gui.single_instance import (
    DesktopCommand,
    DesktopCommandKind,
    DesktopPage,
    DesktopResponse,
    InstanceRole,
    SingleInstanceBroker,
)
from codex_session_manager.review_requests import ReviewOperation, ReviewRequestQueue


class DesktopWindowManager:
    """Route validated desktop commands to idempotent review windows."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.queue = ReviewRequestQueue(paths)
        self._windows: dict[str, TrimReviewWindow | UnifiedMainWindow] = {}
        self._last_window: TrimReviewWindow | UnifiedMainWindow | None = None

    def handle_command(self, command: DesktopCommand) -> DesktopResponse:
        try:
            if command.kind is DesktopCommandKind.ACTIVATE:
                self._activate_or_open_main()
            elif command.kind is DesktopCommandKind.OPEN_PAGE:
                assert command.page is not None
                self._open_page(command.page)
            elif command.kind is DesktopCommandKind.OPEN_THREAD:
                assert command.thread_id is not None
                self._open_thread(command.thread_id)
            elif command.kind is DesktopCommandKind.OPEN_REVIEW_REQUEST:
                assert command.pending_request_path is not None
                self._open_review_request(Path(command.pending_request_path))
        except Exception as exc:
            return DesktopResponse(
                command_id=command.command_id,
                accepted=False,
                message=str(exc),
            )
        return DesktopResponse(command_id=command.command_id, accepted=True)

    def open_pending_requests(self) -> None:
        """Replay requests left behind by an earlier launch or forwarding failure."""

        for pending_path in self.queue.entry_paths():
            try:
                self._open_review_request(pending_path)
            except (OSError, ValueError):
                # Invalid or expired requests remain queued for the future
                # pending-plan page instead of being deleted silently.
                continue

    def _activate_or_open_main(self) -> None:
        existing = self._windows.get("review-shell")
        if existing is not None:
            self._focus(existing)
            return
        self._open_review_window("review-shell", mode=ReviewMode.CONTEXT_TRIM)

    def _open_page(self, page: DesktopPage) -> None:
        review_modes = {
            DesktopPage.CLEANUP: ReviewMode.CONVERSATION_CLEANUP,
            DesktopPage.CONTEXT: ReviewMode.CONTEXT_TRIM,
            DesktopPage.MEMORY: ReviewMode.MEMORY_EDIT,
        }
        mode = review_modes.get(page)
        if mode is not None:
            existing = self._windows.get("review-shell")
            if existing is None:
                self._open_review_window("review-shell", mode=mode)
                return
            if not isinstance(existing, TrimReviewWindow):
                raise ValueError("review-shell key is not bound to the original review GUI")
            existing.set_review_mode(mode)
            self._focus(existing)
            return

        existing = self._windows.get("workspace")
        if existing is None:
            self._open_workspace("workspace", page)
            return
        if not isinstance(existing, UnifiedMainWindow):
            raise ValueError("workspace key is not bound to the unified main window")
        existing.open_page(page)
        self._focus(existing)

    def _open_thread(self, thread_id: str) -> None:
        existing = self._windows.get("review-shell")
        if existing is not None:
            if not isinstance(existing, TrimReviewWindow):
                raise ValueError("review-shell key is not bound to the original review GUI")
            existing.set_review_mode(ReviewMode.CONTEXT_TRIM, refresh=False)
            existing.ui.threadIdEdit.setText(thread_id)
            existing.load_thread(thread_id)
            self._focus(existing)
            return
        self._open_review_window(
            "review-shell",
            thread_id=thread_id,
            load_task_list=True,
            mode=ReviewMode.CONTEXT_TRIM,
        )

    def _open_review_request(self, pending_path: Path) -> None:
        request = self.queue.load_request(pending_path)
        key = f"request:{request.request_id}"
        existing = self._windows.get(key)
        if existing is not None:
            self._focus(existing)
            self.queue.acknowledge(request)
            return

        if request.operation in {
            ReviewOperation.CONVERSATION_CLEANUP,
            ReviewOperation.CONTEXT_TRIM,
            ReviewOperation.MEMORY_EDIT,
        }:
            mode = ReviewMode(request.operation.value)
            review_window = self._open_review_window(
                key,
                load_task_list=False,
                show=False,
                mode=mode,
            )
            review_window.load_review_request(request)
            window: TrimReviewWindow | UnifiedMainWindow = review_window
        else:
            window = self._open_workspace(
                key,
                DesktopPage.BACKUP_RESTORE,
                show=False,
            )
            window.load_request(request)
        self._focus(window)
        self.queue.acknowledge(request)

    def _open_workspace(
        self,
        key: str,
        page: DesktopPage,
        *,
        show: bool = True,
    ) -> UnifiedMainWindow:
        window = UnifiedMainWindow(self.paths)
        window.open_thread_requested.connect(self._open_thread)
        window.open_review_requested.connect(lambda path: self._open_review_request(Path(path)))
        self._register_window(key, window)
        window.open_page(page)
        if show:
            self._focus(window)
        return window

    def _open_review_window(
        self,
        key: str,
        *,
        thread_id: str | None = None,
        load_task_list: bool = True,
        show: bool = True,
        mode: ReviewMode = ReviewMode.CONTEXT_TRIM,
    ) -> TrimReviewWindow:
        window = TrimReviewWindow(
            paths=self.paths,
            thread_id=thread_id,
            load_task_list=load_task_list,
            mode=mode,
        )
        self._register_window(key, window)
        if show:
            self._focus(window)
        return window

    def _register_window(
        self,
        key: str,
        window: TrimReviewWindow | UnifiedMainWindow,
    ) -> None:
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.window_closed.connect(
            lambda key=key, window=window: self._forget_window(key, window)
        )
        self._windows[key] = window
        self._last_window = window

    def _forget_window(
        self,
        key: str,
        window: TrimReviewWindow | UnifiedMainWindow,
    ) -> None:
        if self._windows.get(key) is window:
            self._windows.pop(key, None)
        if self._last_window is window:
            self._last_window = next(reversed(tuple(self._windows.values())), None)

    @staticmethod
    def _focus(window: TrimReviewWindow | UnifiedMainWindow) -> None:
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()


def run_gui(
    *,
    thread_id: str | None = None,
    request_path: Path | None = None,
    page: DesktopPage | None = None,
) -> int:
    targets = sum(value is not None for value in (thread_id, request_path, page))
    if targets > 1:
        raise ValueError("--thread, --request and --page cannot be used together")

    paths = get_paths()
    paths.ensure()
    command: DesktopCommand
    if request_path is not None:
        _request, pending_path = ReviewRequestQueue(paths).enqueue(request_path)
        command = DesktopCommand.open_review_request(pending_path)
    elif thread_id is not None:
        command = DesktopCommand.open_thread(thread_id)
    elif page is not None:
        command = DesktopCommand.open_page(page)
    else:
        command = DesktopCommand.activate()

    app, _owned = ensure_application()
    windows = DesktopWindowManager(paths)
    broker = SingleInstanceBroker(paths)
    role, forwarded_response = broker.acquire_or_forward(command, windows.handle_command)
    if role is InstanceRole.FORWARDED:
        if forwarded_response is None:
            raise OSError("桌面主进程未返回确认")
        if not forwarded_response.accepted:
            raise ValueError(forwarded_response.message or "桌面主进程拒绝了请求")
        return 0

    initial_response = windows.handle_command(command)
    if not initial_response.accepted:
        broker.close()
        raise ValueError(initial_response.message or "无法打开桌面窗口")
    QTimer.singleShot(0, windows.open_pending_requests)
    smoke_exit = os.environ.get("CSM_GUI_SMOKE_EXIT_MS")
    if smoke_exit:
        QTimer.singleShot(max(0, int(smoke_exit)), app.quit)
    try:
        return app.exec()
    finally:
        broker.close()
