"""Read-only pending review and saved trim-plan center."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codex_session_manager.config import AppPaths
from codex_session_manager.pending import (
    PendingEntryKind,
    PendingEntryState,
    PendingPlanEntry,
    PendingPlanStore,
)
from codex_session_manager.pending_plans import PendingPlanStatus, PendingTrimPlanStore
from codex_session_manager.pending_service import PendingPlanService


class PendingPlansPage(QWidget):
    """List persisted work without applying plans or deleting invalid entries."""

    open_review_requested = Signal(str)
    open_thread_requested = Signal(str)
    check_requested = Signal(str)
    cancel_requested = Signal(str)
    pending_changed = Signal()
    pending_changed = Signal()

    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = PendingPlanStore(paths)
        self.pending_store = PendingTrimPlanStore(paths)
        self.pending_service = PendingPlanService(self.pending_store)
        self.pending_trim_store = PendingTrimPlanStore(paths)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("待处理计划")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)

        self.status_label = QLabel(
            "这里汇总尚未被桌面接收的审查请求，以及已经保存但尚未应用的 TrimPlan。"
            "打开条目只进入复核页面，不直接执行写入。"
        )
        self.status_label.setObjectName("workspacePageStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("pendingPlanTree")
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(("类型", "状态", "目标", "来源", "创建时间", "说明"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAccessibleName("待处理审查请求和裁剪计划")
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        self.open_button = QPushButton("打开复核")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        actions.addWidget(self.open_button)
        self.check_button = QPushButton("检查状态")
        self.check_button.setEnabled(False)
        self.check_button.clicked.connect(self._check_selected)
        actions.addWidget(self.check_button)
        self.cancel_button = QPushButton("取消计划")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_selected)
        actions.addWidget(self.cancel_button)
        self.cancel_button = QPushButton("取消计划")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_selected)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

    def refresh(self) -> None:
        entries = self.store.list_entries()
        self.tree.clear()
        for entry in entries:
            self.tree.addTopLevelItem(self._item_for(entry))
        for column in range(5):
            self.tree.resizeColumnToContents(column)
        ready = sum(entry.state is PendingEntryState.READY for entry in entries)
        invalid = len(entries) - ready
        self.status_label.setText(
            f"共 {len(entries)} 个条目：可复核 {ready} 个，校验失败 {invalid} 个。"
            "校验失败条目会保留，等待用户在后续管理流程中处理。"
        )
        self._selection_changed()

    @staticmethod
    def _item_for(entry: PendingPlanEntry) -> QTreeWidgetItem:
        created = PendingPlansPage._format_datetime(entry.created_at)
        kind_label = {
            PendingEntryKind.REVIEW_REQUEST: "审查请求",
            PendingEntryKind.PENDING_TRIM_PLAN: "待处理上下文方案",
            PendingEntryKind.TRIM_PLAN: "上下文方案",
        }[entry.kind]
        state_label = "可复核" if entry.state is PendingEntryState.READY else "校验失败"
        summary = entry.summary if entry.error is None else f"{entry.summary} {entry.error}"
        item = QTreeWidgetItem(
            (
                kind_label,
                state_label,
                entry.target_id or "—",
                entry.source or "—",
                created,
                summary,
            )
        )
        item.setData(0, Qt.ItemDataRole.UserRole, entry.model_dump(mode="json"))
        if entry.state is PendingEntryState.INVALID:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        return item

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return "—"
        return value.astimezone().strftime("%Y-%m-%d %H:%M")

    def _selected_entry(self) -> PendingPlanEntry | None:
        selected = self.tree.selectedItems()
        if len(selected) != 1:
            return None
        payload = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        try:
            return PendingPlanEntry.model_validate(payload)
        except ValueError:
            return None

    def _selection_changed(self) -> None:
        entry = self._selected_entry()
        self.open_button.setEnabled(entry is not None and entry.state is PendingEntryState.READY)
        pending = entry is not None and entry.kind is PendingEntryKind.PENDING_TRIM_PLAN
        self.check_button.setEnabled(pending)
        self.cancel_button.setEnabled(pending)

    def _check_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.kind is not PendingEntryKind.PENDING_TRIM_PLAN:
            return
        self.check_requested.emit(entry.entry_id)

    def _open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.state is not PendingEntryState.READY:
            return
        if entry.kind is PendingEntryKind.REVIEW_REQUEST:
            self.open_review_requested.emit(entry.path)
        elif entry.target_id:
            self.open_thread_requested.emit(entry.target_id)

    def _cancel_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.kind is not PendingEntryKind.PENDING_TRIM_PLAN:
            return
        try:
            pending = self.pending_trim_store.load(Path(entry.path))
        except (OSError, ValueError):
            return
        if pending.status in {PendingPlanStatus.APPLIED, PendingPlanStatus.CANCELLED}:
            return
        self.pending_trim_store.transition(pending, PendingPlanStatus.CANCELLED)
        self.refresh()
