"""Small Qt widgets that keep generated Designer UI declarative."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSplitter

from codex_session_manager.gui.theme import SPLITTER_LINE


class CenteredHandleSplitter(QSplitter):
    """Keep a wide drag target while painting a single centered separator pixel."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(SPLITTER_LINE), 1))
        for handle_index in range(self.count() - 1):
            handle = self.handle(handle_index)
            if handle is None or not handle.isVisible():
                continue
            geometry = handle.geometry()
            x = geometry.left() + (geometry.width() // 2)
            painter.drawLine(x, geometry.top(), x, geometry.bottom())
