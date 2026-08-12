"""Standalone GUI entry point."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer

from codex_session_manager.gui.application import ensure_application
from codex_session_manager.gui.controller import TrimReviewWindow


def run_gui(*, thread_id: str | None = None) -> int:
    app, _owned = ensure_application()
    window = TrimReviewWindow(thread_id=thread_id)
    window.show()
    smoke_exit = os.environ.get("CSM_GUI_SMOKE_EXIT_MS")
    if smoke_exit:
        QTimer.singleShot(max(0, int(smoke_exit)), app.quit)
    return app.exec()
