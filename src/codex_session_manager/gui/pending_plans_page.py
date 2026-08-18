"""Pending review and delayed TrimPlan center."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QThreadPool, Signal
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
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.pending import (
    PendingEntryKind,
    PendingEntryState,
    PendingPlanEntry,
    PendingPlanStore,
)
from codex_session_manager.workflows import ApplicationWorkflows, PendingTrimInspection


class PendingPlansPage(QWidget):
    """Recheck delayed plans before opening the original context-review GUI."""

    open_review_requested = Signal(str)
    open_thread_requested = Signal(str)
    open_pending_requested = Signal(str)
    pending_changed = Signal()

    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = PendingPlanStore(paths)
        self.workflows = ApplicationWorkflows(paths=paths, request_timeout=45)
        self.thread_pool = QThreadPool.globalInstance()
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("待处理计划")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)

        self.status_label = QLabel(
            "这里汇总未被桌面接收的审查请求、已保存 TrimPlan，以及 Hook 创建的"
            "待处理上下文计划。Hook 计划必须重新检查内容、能力和任务状态后才能继续。"
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
        self.check_button = QPushButton("检查状态")
        self.check_button.setEnabled(False)
        self.check_button.clicked.connect(self._check_selected)
        actions.addWidget(self.check_button)
        self.open_button = QPushButton("打开复核")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        actions.addWidget(self.open_button)
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
        counts = {
            state: sum(entry.state is state for entry in entries) for state in PendingEntryState
        }
        self.status_label.setText(
            f"共 {len(entries)} 个条目：等待 {counts[PendingEntryState.WAITING]}，"
            f"可复核 {counts[PendingEntryState.READY]}，"
            f"已结束 {counts[PendingEntryState.TERMINAL]}，"
            f"校验失败 {counts[PendingEntryState.INVALID]}。"
        )
        self._selection_changed()

    @staticmethod
    def _item_for(entry: PendingPlanEntry) -> QTreeWidgetItem:
        created = PendingPlansPage._format_datetime(entry.created_at)
        kind_label = {
            PendingEntryKind.REVIEW_REQUEST: "审查请求",
            PendingEntryKind.PENDING_TRIM_PLAN: "Hook 上下文方案",
            PendingEntryKind.TRIM_PLAN: "上下文方案",
        }[entry.kind]
        state_label = {
            PendingEntryState.WAITING: "等待复核",
            PendingEntryState.READY: "可复核",
            PendingEntryState.TERMINAL: entry.lifecycle_status or "已结束",
            PendingEntryState.INVALID: "校验失败",
        }[entry.state]
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
        actionable = (
            entry is not None
            and entry.kind is PendingEntryKind.PENDING_TRIM_PLAN
            and entry.state
            in {
                PendingEntryState.WAITING,
                PendingEntryState.READY,
            }
        )
        self.check_button.setEnabled(bool(actionable) and not self._busy)
        self.cancel_button.setEnabled(bool(actionable) and not self._busy)
        self.open_button.setEnabled(
            entry is not None and entry.state is PendingEntryState.READY and not self._busy
        )
        self.refresh_button.setEnabled(not self._busy)

    def _check_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.kind is not PendingEntryKind.PENDING_TRIM_PLAN or self._busy:
            return
        self._busy = True
        self.status_label.setText("正在重新读取 App Server 状态并复核计划…")
        self._selection_changed()

        def inspect() -> PendingTrimInspection:
            return self.workflows.inspect_pending_trim_plan(entry.entry_id)

        worker = FunctionWorker(inspect, self)
        worker.signals.result.connect(self._check_succeeded)
        worker.signals.error.connect(self._check_failed)
        worker.signals.finished.connect(self._check_finished)
        self.thread_pool.start(worker)

    def _check_succeeded(self, value: object) -> None:
        if not isinstance(value, PendingTrimInspection):
            self.status_label.setText("待处理计划检查返回了异常结果。")
            return
        self.status_label.setText(f"计划 {value.plan.plan_id} 检查结果：{value.result.value}。")
        self.pending_changed.emit()

    def _check_failed(self, message: str) -> None:
        self.status_label.setText(f"待处理计划检查失败：{message}")

    def _check_finished(self) -> None:
        self._busy = False
        self.refresh()

    def _open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.state is not PendingEntryState.READY:
            return
        if entry.kind is PendingEntryKind.REVIEW_REQUEST:
            self.open_review_requested.emit(entry.path)
        elif entry.kind is PendingEntryKind.PENDING_TRIM_PLAN:
            self.open_pending_requested.emit(entry.entry_id)
        elif entry.target_id:
            self.open_thread_requested.emit(entry.target_id)

    def _cancel_selected(self) -> None:
        entry = self._selected_entry()
        if (
            entry is None
            or entry.kind is not PendingEntryKind.PENDING_TRIM_PLAN
            or entry.state not in {PendingEntryState.WAITING, PendingEntryState.READY}
            or self._busy
        ):
            return
        try:
            self.workflows.cancel_pending_trim_plan(entry.entry_id)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"取消待处理计划失败：{exc}")
            return
        self.pending_changed.emit()
        self.refresh()
