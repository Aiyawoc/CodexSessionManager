"""Virtualized hierarchical turn/item timeline model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt

from codex_session_manager.gui.i18n import (
    DEFAULT_LANGUAGE,
    GuiLanguage,
    action_label,
    compact_number,
    item_kind_label,
    localized_reason,
    text,
    turn_status_label,
)
from codex_session_manager.models import (
    ItemKind,
    ThreadItemSnapshot,
    ThreadSnapshot,
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
    def __init__(
        self,
        snapshot: ThreadSnapshot,
        selections: dict[str, TrimSelection],
        parent: Any = None,
        *,
        language: GuiLanguage = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.selections = selections
        self.language = language
        self.root = TimelineNode(snapshot)
        self.hidden_internal_item_count = 0
        for turn in snapshot.turns:
            turn_node = TimelineNode(turn, self.root)
            self.root.children.append(turn_node)
            visible_items = [item for item in turn.items if self._is_visible_item(item)]
            self.hidden_internal_item_count += len(turn.items) - len(visible_items)
            turn_node.children.extend(TimelineNode(item, turn_node) for item in visible_items)

    @property
    def input_tokens(self) -> int:
        """Locally estimated model-input tokens from normalized item roles."""

        input_kinds = {
            ItemKind.USER_MESSAGE,
            ItemKind.DEVELOPER_MESSAGE,
            ItemKind.SYSTEM_MESSAGE,
            ItemKind.TOOL_RESULT,
            ItemKind.APPROVAL,
        }
        return sum(
            item.token_estimate
            for turn in self.snapshot.turns
            for item in turn.items
            if item.kind in input_kinds
        )

    @property
    def output_tokens(self) -> int:
        """Locally estimated model-output tokens for the remaining items."""

        return max(0, self.snapshot.token_estimate - self.input_tokens)

    def columnCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 4

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
                text(
                    self.language,
                    "turn",
                    number=self.snapshot.turns.index(target) + 1,
                ),
                turn_status_label(self.language, target.status),
                compact_number(sum(item.token_estimate for item in target.items)),
                self._action_text(target.id),
            )
        elif isinstance(target, ThreadItemSnapshot):
            preview = target.text.replace("\n", " ")[:42] or target.id
            values = (
                preview,
                item_kind_label(self.language, target.kind),
                compact_number(target.token_estimate),
                self._action_text(target.id),
            )
        else:
            values = (
                target.title or target.id,
                target.status.value,
                compact_number(target.token_estimate),
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
            headers = (
                text(self.language, "timeline_header_name"),
                text(self.language, "timeline_header_type"),
                text(self.language, "timeline_header_token"),
                text(self.language, "timeline_header_action"),
            )
            return headers[section]
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

    def set_language(self, language: GuiLanguage) -> None:
        """Retranslate model headers and visible cells without rebuilding nodes."""

        if language is self.language:
            return
        self.language = language
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        if self.root.children:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.root.children) - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.DisplayRole],
            )
        for turn_row, turn_node in enumerate(self.root.children):
            if not turn_node.children:
                continue
            parent_index = self.index(turn_row, 0)
            self.dataChanged.emit(
                self.index(0, 0, parent_index),
                self.index(
                    len(turn_node.children) - 1,
                    self.columnCount() - 1,
                    parent_index,
                ),
                [Qt.ItemDataRole.DisplayRole],
            )

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
        return (
            action_label(self.language, action.action)
            if action
            else text(self.language, "action_inherit")
        )

    @staticmethod
    def _is_visible_item(item: ThreadItemSnapshot) -> bool:
        """Hide empty protocol bookkeeping while retaining the full snapshot."""

        return item.token_estimate > 0 or bool(item.text.strip())

    def _tooltip(self, target: TurnSnapshot | ThreadItemSnapshot | ThreadSnapshot) -> str:
        if isinstance(target, ThreadItemSnapshot):
            reasons = "；".join(
                localized_reason(self.language, reason) for reason in target.protected_reasons
            )
            return f"{target.id}\n{reasons}" if reasons else target.id
        return target.id
