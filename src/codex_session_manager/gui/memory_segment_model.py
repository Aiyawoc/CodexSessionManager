"""Flat Qt model for locally parsed memory segments."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from codex_session_manager.gui.i18n import DEFAULT_LANGUAGE, GuiLanguage
from codex_session_manager.memory import (
    MemoryAction,
    MemorySegment,
    MemorySelection,
    MemorySnapshot,
)


class MemorySegmentModel(QAbstractTableModel):
    def __init__(
        self,
        snapshot: MemorySnapshot,
        selections: dict[str, MemorySelection],
        parent: Any = None,
        *,
        language: GuiLanguage = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.selections = selections
        self.language = language

    def rowCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self.snapshot.segments)

    def columnCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 4

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.snapshot.segments):
            return None
        segment = self.snapshot.segments[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return segment
        if role == Qt.ItemDataRole.ToolTipRole:
            heading = " / ".join(segment.heading_path) or "—"
            protection = segment.protection_reason or "—"
            return (
                f"segment: {segment.segment_id}\n"
                f"heading: {heading}\n"
                f"bytes: {segment.start_byte}-{segment.end_byte}\n"
                f"protection: {protection}"
            )
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        selection = self.selections.get(segment.segment_id)
        action = selection.action if selection is not None else MemoryAction.KEEP
        preview = " ".join(segment.text.strip().split())[:72] or "（结构空白）"
        if segment.heading_path and segment.kind.value not in {"heading", "front_matter"}:
            preview = f"{' / '.join(segment.heading_path)} · {preview}"
        labels_zh = {
            MemoryAction.KEEP: "保留",
            MemoryAction.DELETE: "删除",
            MemoryAction.REPLACE: "替换",
            MemoryAction.PROTECT: "保护",
        }
        labels_en = {
            MemoryAction.KEEP: "Keep",
            MemoryAction.DELETE: "Delete",
            MemoryAction.REPLACE: "Replace",
            MemoryAction.PROTECT: "Protect",
        }
        values = (
            preview,
            segment.kind.value,
            str(segment.end_byte - segment.start_byte),
            (labels_en if self.language is GuiLanguage.EN_US else labels_zh)[action],
        )
        return values[index.column()]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation is not Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        headers = (
            ("Segment", "Type", "Bytes", "Action")
            if self.language is GuiLanguage.EN_US
            else ("分段", "类型", "字节", "动作")
        )
        return headers[section]

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def segment_for(self, index: QModelIndex | QPersistentModelIndex) -> MemorySegment | None:
        if not index.isValid() or not 0 <= index.row() < len(self.snapshot.segments):
            return None
        return self.snapshot.segments[index.row()]

    def set_language(self, language: GuiLanguage) -> None:
        if language is self.language:
            return
        self.language = language
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)
        self.refresh_actions()

    def refresh_actions(self) -> None:
        if not self.snapshot.segments:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self.snapshot.segments) - 1, 3),
            [Qt.ItemDataRole.DisplayRole],
        )
