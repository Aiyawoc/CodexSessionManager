"""Fail-open PreCompact prompt and modal review bridge."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QEventLoop, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog

from codex_session_manager.gui.application import ensure_application
from codex_session_manager.gui.controller import TrimReviewWindow
from codex_session_manager.gui.ui_precompact_prompt import Ui_PrecompactPrompt
from codex_session_manager.models import TrimPlan


class PrecompactPromptDialog(QDialog):
    def __init__(self, *, seconds: int, parent: Any = None) -> None:
        super().__init__(parent)
        self.ui = Ui_PrecompactPrompt()
        self.ui.setupUi(self)  # type: ignore[no-untyped-call]
        self.remaining = max(1, seconds)
        self.ui.countdownProgress.setMaximum(self.remaining)
        self.ui.countdownProgress.setValue(self.remaining)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.ui.continueButton.clicked.connect(self.reject)
        self.ui.reviewButton.clicked.connect(self.accept)
        self.timer.start()

    @Slot()
    def _tick(self) -> None:
        self.remaining -= 1
        self.ui.countdownProgress.setValue(max(0, self.remaining))
        if self.remaining <= 0:
            self.reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.reject()
        event.accept()


def review_precompact(
    *,
    thread_id: str,
    turn_id: str,
    trigger: str,
    cwd: str,
    prompt_seconds: int,
    deadline: float,
) -> TrimPlan | None:
    """Return a saved plan or ``None``; every close/error/timeout is fail-open."""

    _app, _owned = ensure_application()
    remaining = int(max(0, min(prompt_seconds, deadline - time.monotonic())))
    if remaining <= 0:
        return None
    prompt = PrecompactPromptDialog(seconds=remaining)
    if prompt.exec() != QDialog.DialogCode.Accepted:
        return None
    remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
    if remaining_ms <= 0:
        return None
    window = TrimReviewWindow(
        thread_id=thread_id,
        trigger="hook",
        source_turn_id=turn_id,
        hook_mode=True,
        load_task_list=False,
    )
    result: list[TrimPlan] = []
    loop = QEventLoop()
    deadline_timer = QTimer()
    deadline_timer.setSingleShot(True)
    deadline_timer.timeout.connect(window.close)
    deadline_timer.timeout.connect(loop.quit)

    def saved(value: object) -> None:
        if isinstance(value, TrimPlan):
            result.append(value)
        loop.quit()

    window.plan_saved.connect(saved)
    window.window_closed.connect(loop.quit)
    window.ui.taskContextStatusLabel.setToolTip(f"cwd={cwd}")
    window.show()
    deadline_timer.start(remaining_ms)
    loop.exec()
    deadline_timer.stop()
    if window.isVisible():
        window.close()
    return result[0] if result else None
