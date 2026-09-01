"""Read-only conversation-cleanup suggestion review page."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codex_session_manager.cleanup_review import prepare_cleanup_action_plan
from codex_session_manager.config import AppPaths
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.models import ActionPlan
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    SuggestedAction,
    SuggestionBundleStore,
    SuggestionTarget,
)


class ConversationCleanupPage(QWidget):
    """Display sealed cleanup suggestions while keeping execution disabled."""

    plan_created = Signal(object)

    def __init__(
        self,
        paths: AppPaths,
        parent: QWidget | None = None,
        plan_builder: Callable[[ReviewRequest, tuple[str, ...]], ActionPlan] | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.request: ReviewRequest | None = None
        self.current_plan: ActionPlan | None = None
        self.plan_builder = plan_builder or (
            lambda request, selected_ids: prepare_cleanup_action_plan(
                self.paths,
                request,
                selected_ids,
            )
        )
        self.thread_pool = QThreadPool.globalInstance()
        self._worker_owner = QApplication.instance() or self
        self._planning = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("对话清理审查")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)

        self.status_label = QLabel("尚未加载审查请求。当前页面只调整建议选择，不执行任务写入。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("workspacePageStatus")
        root.addWidget(self.status_label)

        notice = QFrame()
        notice.setObjectName("workspaceNotice")
        notice_layout = QVBoxLayout(notice)
        notice_layout.setContentsMargins(12, 10, 12, 10)
        notice_layout.addWidget(
            QLabel(
                "安全边界：建议不是执行授权。备份、归档和反归档由项目与任务界面"
                "分别发起，并在执行前重新读取真实状态、展开全部派生后代和复核不可变计划。"
            )
        )
        root.addWidget(notice)

        self.tree = QTreeWidget()
        self.tree.setObjectName("cleanupSuggestionTree")
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(("建议目标", "动作", "置信度", "理由", "内容指纹"))
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAccessibleName("对话清理建议列表")
        self.tree.itemChanged.connect(self._selection_changed)
        root.addWidget(self.tree, 1)

        footer = QHBoxLayout()
        self.selection_label = QLabel("已选择 0 个归档建议")
        footer.addWidget(self.selection_label)
        footer.addStretch(1)
        self.create_plan_button = QPushButton("生成最终计划")
        self.create_plan_button.setEnabled(False)
        self.create_plan_button.setToolTip(
            "重新读取当前 App Server 状态、复核建议指纹与后代闭包，并保存不可变 ActionPlan；不会执行归档。"
        )
        self.create_plan_button.clicked.connect(self._create_plan)
        footer.addWidget(self.create_plan_button)
        root.addLayout(footer)

    def load_request(self, request: ReviewRequest) -> None:
        if request.operation is not ReviewOperation.CONVERSATION_CLEANUP:
            raise ValueError("ConversationCleanupPage only accepts conversation_cleanup")
        self.request = request
        self.current_plan = None
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            targets: tuple[SuggestionTarget, ...] = ()
            if request.suggestion_bundle_path:
                bundle = SuggestionBundleStore(self.paths).load(
                    Path(request.suggestion_bundle_path)
                )
                if bundle.operation is not ReviewOperation.CONVERSATION_CLEANUP:
                    raise ValueError("cleanup suggestion bundle operation mismatch")
                targets = bundle.targets

            if targets:
                for target in targets:
                    self._append_target(target)
            else:
                for target_id in request.target_ids:
                    item = QTreeWidgetItem((target_id, "待审查", "—", "未附带建议包", "—"))
                    item.setData(0, Qt.ItemDataRole.UserRole, target_id)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    self.tree.addTopLevelItem(item)
        finally:
            self.tree.blockSignals(False)

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(2)
        self.tree.resizeColumnToContents(4)
        self.status_label.setText(
            f"已加载请求 {request.request_id}，共 {self.tree.topLevelItemCount()} 个建议目标。"
            "可取消建议选择；生成最终计划仍不会执行归档。"
        )
        self._selection_changed()

    def selected_target_ids(self) -> tuple[str, ...]:
        selected: list[str] = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is None:
                continue
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            target_id = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(target_id, str):
                selected.append(target_id)
        return tuple(selected)

    def _append_target(self, target: SuggestionTarget) -> None:
        target_label = target.target_id or target.target_path or "未知目标"
        confidence = f"{target.confidence * 100:.0f}%"
        item = QTreeWidgetItem(
            (
                target_label,
                target.suggested_action.value,
                confidence,
                target.reason,
                target.source_fingerprint[:16],
            )
        )
        item.setData(0, Qt.ItemDataRole.UserRole, target.target_id or target.target_path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            Qt.CheckState.Checked
            if target.suggested_action is SuggestedAction.ARCHIVE
            else Qt.CheckState.Unchecked,
        )
        self.tree.addTopLevelItem(item)

    def _selection_changed(self, _item: QTreeWidgetItem | None = None, _column: int = 0) -> None:
        selected_count = len(self.selected_target_ids())
        self.selection_label.setText(
            f"已选择 {selected_count} 个归档建议"
            + (
                f"；当前计划 {self.current_plan.plan_id}"
                if self.current_plan is not None
                else "（尚未生成执行计划）"
            )
        )
        self.create_plan_button.setEnabled(
            not self._planning
            and self.request is not None
            and self.request.suggestion_bundle_path is not None
            and selected_count > 0
        )

    def _create_plan(self) -> None:
        request = self.request
        selected_ids = self.selected_target_ids()
        if request is None or not selected_ids or self._planning:
            return
        self._planning = True
        self.current_plan = None
        self.create_plan_button.setText("正在复核…")
        self.status_label.setText(
            "正在重新读取当前 App Server 状态，并复核建议指纹、目标状态和派生后代闭包…"
        )
        self._selection_changed()
        worker = FunctionWorker(
            lambda: self.plan_builder(request, selected_ids),
            owner=self._worker_owner,
        )
        worker.signals.result.connect(self._plan_ready)
        worker.signals.error.connect(self._plan_failed)
        worker.signals.finished.connect(self._plan_finished)
        self.thread_pool.start(worker)

    def _plan_ready(self, value: object) -> None:
        if not isinstance(value, ActionPlan):
            self._plan_failed("清理计划生成器返回了异常结果。")
            return
        self.current_plan = value
        affected = {
            thread_id for target in value.targets for thread_id in target.affected_thread_ids
        }
        self.status_label.setText(
            f"最终计划 {value.plan_id} 已安全保存：根目标 {len(value.targets)} 个，"
            f"包含派生后代共 {len(affected)} 个对话。尚未创建备份，也未执行归档。"
        )
        self.plan_created.emit(value)

    def _plan_failed(self, message: str) -> None:
        self.current_plan = None
        self.status_label.setText(f"无法生成最终清理计划：{message}")

    def _plan_finished(self) -> None:
        self._planning = False
        self.create_plan_button.setText("重新生成最终计划")
        self._selection_changed()
