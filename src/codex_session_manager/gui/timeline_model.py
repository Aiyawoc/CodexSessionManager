"""Virtualized hierarchical turn/item timeline model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt

from codex_session_manager.models import (
    ThreadItemSnapshot,
    ThreadSnapshot,
    TrimAction,
    TrimSelection,
    TurnSnapshot,
)


@dataclass(slots=True)
class TimelineNode:
    target: ThreadSnapshot | TurnSnapshot | ThreadItemSnapshot | None
    parent: TimelineNode | None = None
    children: list[TimelineNode] = field(default_factory=list)

    @property
    def target_id(self) -> str | None:
        return getattr(self.target, "id", None)


class TurnTimelineModel(QAbstractItemModel):
    HEADERS = ("时间线", "类型/状态", "Token", "动作")

    def __init__(
        self,
        snapshot: ThreadSnapshot,
        selections: dict[str, TrimSelection],
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.selections = selections
        self.root = TimelineNode(snapshot)
        for turn in snapshot.turns:
            turn_node = TimelineNode(turn, self.root)
            self.root.children.append(turn_node)
            turn_node.children.extend(TimelineNode(item, turn_node) for item in turn.items)

    def columnCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self.HEADERS)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        node = self._node(parent or QModelIndex())
        return len(node.children)

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex | None = None,
    ) -> QModelIndex:
        parent_index = parent or QModelIndex()
        if not self.hasIndex(row, column, parent_index):
            return QModelIndex()
        parent_node = self._node(parent_index)
        return self.createIndex(row, column, parent_node.children[row])

    def parent(  # type: ignore[override]
        self, index: QModelIndex | QPersistentModelIndex
    ) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = self._node(index)
        parent_node = node.parent
        if parent_node is None or parent_node is self.root:
            return QModelIndex()
        grandparent = parent_node.parent
        if grandparent is None:
            return QModelIndex()
        return self.createIndex(grandparent.children.index(parent_node), 0, parent_node)

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        node = self._node(index)
        target = node.target
        if target is None:
            return None
        if role == Qt.ItemDataRole.UserRole:
            return target
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(target)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if isinstance(target, TurnSnapshot):
            values = (
                f"Turn {self.snapshot.turns.index(target) + 1}",
                target.status,
                str(sum(item.token_estimate for item in target.items)),
                self._action_text(target.id),
            )
        elif isinstance(target, ThreadItemSnapshot):
            preview = target.text.replace("\n", " ")[:42] or target.id
            values = (
                preview,
                target.kind.value,
                str(target.token_estimate),
                self._action_text(target.id),
            )
        else:
            values = (
                target.title or target.id,
                target.status.value,
                str(target.token_estimate),
                "",
            )
        return values[index.column()]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def refresh_actions(self) -> None:
        if self.root.children:
            top_left = self.index(0, 3)
            bottom_right = self.index(len(self.root.children) - 1, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])
        for turn_row, turn_node in enumerate(self.root.children):
            if turn_node.children:
                parent_index = self.index(turn_row, 0)
                top_left = self.index(0, 3, parent_index)
                bottom_right = self.index(len(turn_node.children) - 1, 3, parent_index)
                self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

    def target_for(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> TurnSnapshot | ThreadItemSnapshot | None:
        target = self._node(index).target
        return target if isinstance(target, (TurnSnapshot, ThreadItemSnapshot)) else None

    def _node(self, index: QModelIndex | QPersistentModelIndex) -> TimelineNode:
        if index.isValid():
            pointer = index.internalPointer()
            if isinstance(pointer, TimelineNode):
                return pointer
        return self.root

    def _action_text(self, target_id: str) -> str:
        action = self.selections.get(target_id)
        labels = {
            TrimAction.KEEP: "保留",
            TrimAction.EXCLUDE: "排除",
            TrimAction.SUMMARY: "摘要",
            TrimAction.PROTECT: "保护",
        }
        return labels.get(action.action, "继承") if action else "继承"

    @staticmethod
    def _tooltip(target: TurnSnapshot | ThreadItemSnapshot | ThreadSnapshot) -> str:
        if isinstance(target, ThreadItemSnapshot):
            reasons = "；".join(target.protected_reasons)
            return f"{target.id}\n{reasons}" if reasons else target.id
        return target.id
