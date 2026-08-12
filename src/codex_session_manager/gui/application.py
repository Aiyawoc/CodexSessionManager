"""Shared QApplication construction and theme setup."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from codex_session_manager.config import get_paths


def ensure_application() -> tuple[QApplication, bool]:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing, False
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName("CodexSessionManager")
    app.setOrganizationName("CodexSessionManager")
    # QtVSCodeStyle writes extracted resources below Path.home() at import
    # time. Redirect that legacy behavior into CSM's bounded cache instead of
    # allowing it to touch an unrelated user-home path.
    with contextlib.suppress(AttributeError, ImportError, OSError):
        cache_home = get_paths().cache_dir / "qtvscodestyle-home"
        cache_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with patch.object(Path, "home", return_value=cache_home):
            import qtvscodestyle as qtvsc

            app.setStyleSheet(qtvsc.load_stylesheet(qtvsc.Theme.LIGHT_VS))
    return app, True
