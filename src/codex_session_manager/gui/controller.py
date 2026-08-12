"""Controller for the Designer-authored context-trimming window."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import QItemSelection, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHeaderView, QMainWindow, QMessageBox, QStyle, QTreeWidgetItem

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.gui.timeline_model import TurnTimelineModel
from codex_session_manager.gui.ui_main_window import Ui_MainWindow
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import (
    CapabilityMatrix,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.plans import PlanStore
from codex_session_manager.trim import (
    LocalTrimSuggester,
    TrimError,
    TrimExecutor,
    validate_selections,
)

ACTION_BY_INDEX = {
    0: TrimAction.KEEP,
    1: TrimAction.EXCLUDE,
    2: TrimAction.SUMMARY,
    3: TrimAction.PROTECT,
}
INDEX_BY_ACTION = {value: key for key, value in ACTION_BY_INDEX.items()}
MAX_PREVIEW_CHARS = 200_000


@dataclass(frozen=True, slots=True)
class ReviewDocument:
    snapshot: ThreadSnapshot
    capabilities: CapabilityMatrix
    suggested_plan: TrimPlan


class TrimReviewWindow(QMainWindow):
    plan_saved = Signal(object)
    derived_created = Signal(str)
    window_closed = Signal()

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        thread_id: str | None = None,
        trigger: Literal["manual", "auto", "hook"] = "manual",
        source_turn_id: str | None = None,
        hook_mode: bool = False,
        load_task_list: bool = True,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)  # type: ignore[no-untyped-call]
        self.paths = paths or get_paths()
        self.paths.ensure()
        self.trigger = trigger
        self.source_turn_id = source_turn_id
        self.hook_mode = hook_mode
        self.thread_pool = QThreadPool.globalInstance()
        self.document: ReviewDocument | None = None
        self.timeline_model: TurnTimelineModel | None = None
        self.task_snapshots: tuple[ThreadSnapshot, ...] = ()
        self.selections: dict[str, TrimSelection] = {}
        self.current_target: TurnSnapshot | ThreadItemSnapshot | None = None
        self.current_plan: TrimPlan | None = None
        self._updating_controls = False
        self._generation = 0
        self._task_generation = 0
        self._task_selection_guard = False
        self._closing = False
        self._write_in_progress = False
        self._task_pane_expanded = True
        self._expanded_splitter_sizes: tuple[int, ...] = (450, 340, 500, 300)
        self._connect_signals()
        self._configure_views()
        self._configure_tool_rail()
        self.ui.errorLabel.hide()
        self.ui.mainSplitter.setSizes([450, 340, 500, 300])
        if hook_mode:
            self.ui.applyButton.hide()
            self.ui.taskPane.hide()
            self.ui.toolRail.hide()
            self.ui.taskPaneCollapseButton.hide()
            self._task_pane_expanded = False
            self.ui.cancelButton.setText("取消并继续原生压缩")
            self.ui.taskContextStatusLabel.setText("Hook 审查模式：只保存计划")
        elif load_task_list:
            self.load_task_list()
        if thread_id:
            self.ui.threadIdEdit.setText(thread_id)
            self.load_thread(thread_id)

    def _configure_views(self) -> None:
        """Apply stable column sizing and comfortable desktop reading metrics."""

        header = self.ui.timelineView.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for section, width in ((1, 100), (2, 55), (3, 65)):
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(section, width)
        self.ui.timelineView.setIndentation(16)
        self.ui.timelineView.setHeaderHidden(False)
        self.ui.timelineView.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ui.contentBrowser.setLineWrapMode(self.ui.contentBrowser.LineWrapMode.WidgetWidth)
        self.ui.summaryEdit.setMinimumHeight(120)
        self.ui.reasonBrowser.setMinimumHeight(72)
        self.ui.heroLayout.setAlignment(self.ui.brandMark, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroLayout.setAlignment(self.ui.heroTextLayout, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroLayout.setAlignment(self.ui.headerBadge, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroTextLayout.setSpacing(0)
        self.ui.footerMainLayout.setStretch(1, 1)
        self.ui.footerLayout.setAlignment(self.ui.footerMainLayout, Qt.AlignmentFlag.AlignVCenter)
        self.ui.footerMainLayout.setAlignment(self.ui.buttonLayout, Qt.AlignmentFlag.AlignVCenter)
        task_header = self.ui.taskListView.header()
        task_header.setStretchLastSection(False)
        task_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        task_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        task_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.ui.taskListView.setColumnWidth(0, 170)
        self.ui.taskListView.setColumnWidth(1, 195)
        self.ui.taskListView.setIndentation(14)
        self.ui.taskListView.setHeaderHidden(False)
        self.ui.mainSplitter.setStretchFactor(0, 0)
        self.ui.mainSplitter.setStretchFactor(1, 1)
        self.ui.mainSplitter.setStretchFactor(2, 1)
        self.ui.mainSplitter.setStretchFactor(3, 0)

    def _configure_tool_rail(self) -> None:
        """Use native platform glyphs for the rail without shipping icon assets."""

        style = self.style()
        icons = (
            (self.ui.projectTaskRailButton, QStyle.StandardPixmap.SP_FileDialogListView),
            (self.ui.backupRailButton, QStyle.StandardPixmap.SP_DriveHDIcon),
            (self.ui.cleanupRailButton, QStyle.StandardPixmap.SP_TrashIcon),
            (self.ui.auditRailButton, QStyle.StandardPixmap.SP_MessageBoxInformation),
        )
        for button, standard_pixmap in icons:
            button.setIcon(style.standardIcon(standard_pixmap))
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(34, 34)
        self.ui.taskPaneCollapseButton.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        )
        self.ui.taskPaneCollapseButton.setIconSize(QSize(18, 18))
        self.ui.taskPaneCollapseButton.setFixedSize(34, 34)
        self.ui.projectTaskRailButton.setChecked(True)

    def _connect_signals(self) -> None:
        self.ui.taskSearchEdit.textChanged.connect(self._filter_task_list)
        self.ui.taskListView.itemSelectionChanged.connect(self._task_selected)
        self.ui.taskRefreshButton.clicked.connect(self.load_task_list)
        self.ui.projectTaskRailButton.clicked.connect(self._toggle_task_pane)
        self.ui.taskPaneCollapseButton.clicked.connect(self._toggle_task_pane)
        self.ui.loadButton.clicked.connect(self._load_from_edit)
        self.ui.threadIdEdit.returnPressed.connect(self._load_from_edit)
        self.ui.actionCombo.currentIndexChanged.connect(self._action_changed)
        self.ui.summaryEdit.textChanged.connect(self._summary_changed)
        self.ui.suggestButton.clicked.connect(self._regenerate_suggestions)
        self.ui.savePlanButton.clicked.connect(self._save_plan)
        self.ui.applyButton.clicked.connect(self._apply_plan)
        self.ui.cancelButton.clicked.connect(self.close)

    @Slot()
    def _toggle_task_pane(self) -> None:
        """Collapse or restore the project/task pane without shrinking the action pane."""

        if self.hook_mode:
            return
        splitter = self.ui.mainSplitter
        if self._task_pane_expanded:
            sizes = splitter.sizes()
            if len(sizes) != 4:
                sizes = list(self._expanded_splitter_sizes)
            self._expanded_splitter_sizes = tuple(sizes)
            task_width = max(0, sizes[0])
            timeline_width = max(1, sizes[1])
            content_width = max(1, sizes[2])
            center_width = timeline_width + content_width
            timeline_gain = round(task_width * timeline_width / center_width)
            # Hiding the first pane also removes its splitter handle; keep that
            # reclaimed 8 px in the center instead of letting Qt widen the
            # fixed-width action pane during redistribution.
            content_gain = task_width - timeline_gain + splitter.handleWidth()
            self.ui.taskPane.hide()
            splitter.setSizes(
                [
                    0,
                    timeline_width + timeline_gain,
                    content_width + content_gain,
                    sizes[3],
                ]
            )
            self._task_pane_expanded = False
            self.ui.taskPaneCollapseButton.setToolTip("收起项目与任务面板")
            self.ui.projectTaskRailButton.setChecked(False)
            return

        self.ui.taskPane.show()
        splitter.setSizes(list(self._expanded_splitter_sizes))
        self._task_pane_expanded = True
        self.ui.taskPaneCollapseButton.setToolTip("收起项目与任务面板")
        self.ui.projectTaskRailButton.setChecked(True)

    def load_task_list(self) -> None:
        """Load lightweight task summaries without blocking the Qt thread."""

        self._task_generation += 1
        generation = self._task_generation
        self.ui.taskRefreshButton.setEnabled(False)
        self.ui.taskListStatusLabel.setText("正在通过 App Server 加载任务列表…")

        def load() -> tuple[ThreadSnapshot, ...]:
            client, _capabilities = connect_and_probe(request_timeout=45)
            try:
                return InventoryService(client).list(
                    include_active=True,
                    include_archived=True,
                    include_turns=False,
                )
            finally:
                client.close()

        worker = FunctionWorker(load)
        worker.signals.result.connect(
            lambda value, current=generation: self._task_list_loaded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._task_list_failed(current, message)
        )
        worker.signals.finished.connect(
            lambda current=generation: self._task_list_finished(current)
        )
        self.thread_pool.start(worker)

    def _task_list_loaded(self, generation: int, value: object) -> None:
        if generation != self._task_generation or self._closing:
            return
        if not isinstance(value, tuple) or not all(
            isinstance(snapshot, ThreadSnapshot) for snapshot in value
        ):
            self._task_list_failed(generation, "任务列表返回类型异常。")
            return
        self.task_snapshots = value
        self._populate_task_list(value)
        self.ui.taskListStatusLabel.setText(f"共 {len(value)} 个任务 · 可按名称或 ID 搜索")

    def _task_list_failed(self, generation: int, message: str) -> None:
        if generation != self._task_generation or self._closing:
            return
        self.ui.taskListStatusLabel.setText("任务列表加载失败；仍可手动输入任务 ID。")
        self._show_error(f"任务列表加载失败：{message}")

    def _task_list_finished(self, generation: int) -> None:
        if generation == self._task_generation and not self._closing:
            self.ui.taskRefreshButton.setEnabled(True)

    @Slot(str)
    def _filter_task_list(self, _query: str) -> None:
        self._populate_task_list(self.task_snapshots)

    @Slot()
    def _task_selected(self) -> None:
        if self._task_selection_guard or self._closing:
            return
        item = self.ui.taskListView.currentItem()
        if item is None:
            return
        thread_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(thread_id, str) or not thread_id:
            return
        self.ui.threadIdEdit.setText(thread_id)
        self.load_thread(thread_id)

    def _populate_task_list(self, snapshots: tuple[ThreadSnapshot, ...]) -> None:
        query = self.ui.taskSearchEdit.text().strip().casefold()
        selected_id = self._selected_task_id()
        groups: dict[str, tuple[str, list[ThreadSnapshot]]] = {}
        for snapshot in snapshots:
            if query and not self._task_matches(snapshot, query):
                continue
            group_key, group_label = self._project_group(snapshot)
            if group_key not in groups:
                groups[group_key] = (group_label, [])
            groups[group_key][1].append(snapshot)

        self._task_selection_guard = True
        try:
            self.ui.taskListView.clear()
            for group_key in sorted(groups, key=str.casefold):
                group_label, members = groups[group_key]
                group = QTreeWidgetItem([group_label, "", ""])
                group.setToolTip(0, self._project_tooltip(members[0]))
                group.setFirstColumnSpanned(True)
                for snapshot in sorted(members, key=self._task_sort_key, reverse=True):
                    title = snapshot.title.strip() or "未命名任务"
                    status = self._status_label(snapshot)
                    item = QTreeWidgetItem([title, snapshot.id, status])
                    item.setData(0, Qt.ItemDataRole.UserRole, snapshot.id)
                    item.setToolTip(0, self._task_tooltip(snapshot))
                    item.setToolTip(1, snapshot.id)
                    group.addChild(item)
                self.ui.taskListView.addTopLevelItem(group)
                group.setExpanded(True)
            if selected_id:
                self._select_task_in_list(selected_id)
        finally:
            self._task_selection_guard = False

    def _select_task_in_list(self, thread_id: str) -> None:
        for group_index in range(self.ui.taskListView.topLevelItemCount()):
            group = self.ui.taskListView.topLevelItem(group_index)
            if group is None:
                continue
            for item_index in range(group.childCount()):
                item = group.child(item_index)
                if item.data(0, Qt.ItemDataRole.UserRole) == thread_id:
                    self.ui.taskListView.setCurrentItem(item)
                    item.setSelected(True)
                    return

    def _selected_task_id(self) -> str | None:
        item = self.ui.taskListView.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    @staticmethod
    def _task_matches(snapshot: ThreadSnapshot, query: str) -> bool:
        haystack = "\n".join(
            value
            for value in (
                snapshot.id,
                snapshot.title,
                snapshot.preview,
                snapshot.cwd or "",
                snapshot.git_remote or "",
            )
            if value
        )
        return query in haystack.casefold()

    @staticmethod
    def _project_group(snapshot: ThreadSnapshot) -> tuple[str, str]:
        if snapshot.cwd:
            path = Path(snapshot.cwd)
            project_name = path.name or str(path)
            return snapshot.cwd, project_name
        if snapshot.git_remote:
            remote = snapshot.git_remote.rstrip("/")
            project_name = remote.rsplit("/", 1)[-1].removesuffix(".git") or remote
            return snapshot.git_remote, project_name
        return "__unknown_project__", "未指定项目"

    @staticmethod
    def _task_sort_key(snapshot: ThreadSnapshot) -> tuple[float, str]:
        timestamp = snapshot.updated_at or snapshot.created_at
        return (timestamp.timestamp() if timestamp else 0.0, snapshot.id)

    @staticmethod
    def _status_label(snapshot: ThreadSnapshot) -> str:
        labels = {
            ThreadStatus.NOT_LOADED: "未加载",
            ThreadStatus.IDLE: "空闲",
            ThreadStatus.ACTIVE: "进行中",
            ThreadStatus.SYSTEM_ERROR: "系统错误",
            ThreadStatus.UNKNOWN: "未知",
        }
        label = labels.get(snapshot.status, snapshot.status.value)
        return f"{label} · 已归档" if snapshot.archived else label

    @staticmethod
    def _task_tooltip(snapshot: ThreadSnapshot) -> str:
        lines = [snapshot.title or "未命名任务", snapshot.id]
        if snapshot.cwd:
            lines.append(f"项目：{snapshot.cwd}")
        if snapshot.git_remote:
            lines.append(f"Git：{snapshot.git_remote}")
        return "\n".join(lines)

    @staticmethod
    def _project_tooltip(snapshot: ThreadSnapshot) -> str:
        lines: list[str] = []
        if snapshot.cwd:
            lines.append(f"项目：{snapshot.cwd}")
        if snapshot.git_remote:
            lines.append(f"Git：{snapshot.git_remote}")
        return "\n".join(lines) or "未指定项目路径或 Git remote"

    @Slot()
    def _load_from_edit(self) -> None:
        thread_id = self.ui.threadIdEdit.text().strip()
        if not thread_id:
            self._show_error("请输入 Codex 任务 ID。")
            return
        self.load_thread(thread_id)

    def load_thread(self, thread_id: str) -> None:
        self._generation += 1
        generation = self._generation
        self._set_busy(True, "正在通过 App Server 加载任务…")

        def load() -> ReviewDocument:
            client, capabilities = connect_and_probe(request_timeout=45)
            try:
                snapshot = InventoryService(client).read(thread_id, include_turns=True)
                suggested = LocalTrimSuggester().suggest(
                    snapshot,
                    capabilities=capabilities,
                    trigger=self.trigger,
                    source_turn_id=self.source_turn_id,
                )
                return ReviewDocument(snapshot, capabilities, suggested)
            finally:
                client.close()

        worker = FunctionWorker(load)
        worker.signals.result.connect(
            lambda value, current=generation: self._document_loaded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._load_failed(current, message)
        )
        worker.signals.finished.connect(lambda current=generation: self._load_finished(current))
        self.thread_pool.start(worker)

    def _document_loaded(self, generation: int, value: object) -> None:
        if generation != self._generation or self._closing:
            return
        if not isinstance(value, ReviewDocument):
            self._show_error("加载结果类型异常。")
            return
        self.document = value
        self.selections = {
            selection.target_id: selection for selection in value.suggested_plan.selections
        }
        self.current_plan = value.suggested_plan
        self.timeline_model = TurnTimelineModel(value.snapshot, self.selections, self)
        self.ui.timelineView.setModel(self.timeline_model)
        self._configure_views()
        self.ui.timelineView.expandToDepth(0)
        self.ui.timelineView.selectionModel().selectionChanged.connect(self._selection_changed)
        task_status = (
            f"{value.snapshot.title or value.snapshot.id} · "
            f"{value.snapshot.status.value} · {len(value.snapshot.turns)} turns"
        )
        self.ui.taskContextStatusLabel.setText(task_status)
        self.ui.taskContextStatusLabel.setToolTip(task_status)
        self._select_task_in_list(value.snapshot.id)
        self.ui.savePlanButton.setEnabled(True)
        self.ui.applyButton.setEnabled(
            not self.hook_mode and value.snapshot.status is not ThreadStatus.ACTIVE
        )
        self._update_estimate()
        if value.snapshot.turns:
            first = self.timeline_model.index(0, 0)
            self.ui.timelineView.setCurrentIndex(first)
        if not value.capabilities.write_enabled:
            self.ui.applyButton.setEnabled(False)
            self._show_error(
                "当前 App Server 能力只能读取和规划："
                + (value.capabilities.read_only_reason or "未知协议")
            )

    def _load_failed(self, generation: int, message: str) -> None:
        if generation != self._generation or self._closing:
            return
        self._show_error(f"加载失败：{message}")

    def _load_finished(self, generation: int) -> None:
        if generation == self._generation and not self._closing:
            self._set_busy(False)

    @Slot(QItemSelection, QItemSelection)
    def _selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        if self.timeline_model is None or not selected.indexes():
            return
        index = selected.indexes()[0]
        target = self.timeline_model.target_for(index)
        if target is None:
            return
        self.current_target = target
        self._show_target(target)

    def _show_target(self, target: TurnSnapshot | ThreadItemSnapshot) -> None:
        self._updating_controls = True
        try:
            if isinstance(target, TurnSnapshot):
                text = "\n\n".join(item.text for item in target.items if item.text)
                meta = f"Turn {target.id} · {target.status} · {len(target.items)} items"
                protected = tuple(
                    dict.fromkeys(
                        reason for item in target.items for reason in item.protected_reasons
                    )
                )
            else:
                text = target.text
                meta = f"Item {target.id} · {target.kind.value} · role={target.role or '—'} · depends={', '.join(target.depends_on) or '—'}"
                protected = target.protected_reasons
            self.ui.contentMetaLabel.setText(meta)
            if len(text) > MAX_PREVIEW_CHARS:
                half = MAX_PREVIEW_CHARS // 2
                text = (
                    text[:half]
                    + "\n\n… [预览已按有界缓存截断；计划仍基于完整 App Server 数据] …\n\n"
                    + text[-half:]
                )
            self.ui.contentBrowser.setPlainText(text or "（无模型可见文本）")
            selection = self.selections.get(target.id)
            action = selection.action if selection else TrimAction.KEEP
            self.ui.actionCombo.setCurrentIndex(INDEX_BY_ACTION[action])
            self.ui.summaryEdit.setPlainText(selection.summary or "" if selection else "")
            self.ui.summaryEdit.setEnabled(action is TrimAction.SUMMARY)
            self.ui.reasonBrowser.setPlainText(selection.reason if selection else "继承 turn 动作")
            if protected:
                self.ui.riskLabel.setText("风险：受保护 · " + "；".join(protected))
            else:
                self.ui.riskLabel.setText("风险：请审查建议后再保存")
        finally:
            self._updating_controls = False

    @Slot(int)
    def _action_changed(self, index: int) -> None:
        if self._updating_controls or self.current_target is None:
            return
        action = ACTION_BY_INDEX[index]
        protected = (
            tuple(reason for item in self.current_target.items for reason in item.protected_reasons)
            if isinstance(self.current_target, TurnSnapshot)
            else self.current_target.protected_reasons
        )
        if protected and action in {TrimAction.EXCLUDE, TrimAction.SUMMARY}:
            self._show_error("该内容包含硬保护项，只能保留或保护。")
            self._show_target(self.current_target)
            return
        existing = self.selections.get(self.current_target.id)
        summary = self.ui.summaryEdit.toPlainText().strip() or None
        if action is TrimAction.SUMMARY and not summary:
            summary = self._target_text(self.current_target)[:1200] or "保留原始来源指纹。"
        self.selections[self.current_target.id] = TrimSelection(
            target_id=self.current_target.id,
            target_level="turn" if isinstance(self.current_target, TurnSnapshot) else "item",
            action=action,
            summary=summary if action is TrimAction.SUMMARY else None,
            reason=existing.reason if existing else "用户手动调整",
            suggested=False,
            protected_reasons=tuple(dict.fromkeys(protected))
            if action is TrimAction.PROTECT
            else (),
        )
        self.ui.summaryEdit.setEnabled(action is TrimAction.SUMMARY)
        if action is TrimAction.SUMMARY:
            self._updating_controls = True
            self.ui.summaryEdit.setPlainText(summary or "")
            self._updating_controls = False
        if self.timeline_model:
            self.timeline_model.refresh_actions()
        self._update_estimate()

    @Slot()
    def _summary_changed(self) -> None:
        if self._updating_controls or self.current_target is None:
            return
        selection = self.selections.get(self.current_target.id)
        if selection is None or selection.action is not TrimAction.SUMMARY:
            return
        text = self.ui.summaryEdit.toPlainText().strip()
        if text:
            self.selections[self.current_target.id] = selection.model_copy(update={"summary": text})
            self._update_estimate()

    @Slot()
    def _regenerate_suggestions(self) -> None:
        if self.document is None:
            return
        if self.ui.aiConsentCheck.isChecked():
            self._show_error("尚未配置内容 AI 提供方；未发送任何内容，已使用本地规则。")
        plan = LocalTrimSuggester().suggest(
            self.document.snapshot,
            capabilities=self.document.capabilities,
            trigger=self.trigger,
            source_turn_id=self.source_turn_id,
        )
        self.selections = {selection.target_id: selection for selection in plan.selections}
        if self.timeline_model:
            self.timeline_model.selections = self.selections
            self.timeline_model.refresh_actions()
        self.current_plan = plan
        if self.current_target:
            self._show_target(self.current_target)
        self._update_estimate()

    def _build_plan(self) -> TrimPlan:
        if self.document is None:
            raise TrimError("no thread is loaded")
        selections = tuple(self.selections.values())
        validate_selections(self.document.snapshot, selections)
        after = self._estimated_after()
        return TrimPlan.create(
            source_thread=self.document.snapshot,
            capability_fingerprint=self.document.capabilities.fingerprint,
            selections=selections,
            estimated_tokens_after=after,
            trigger=self.trigger,
            source_turn_id=self.source_turn_id,
        )

    @Slot()
    def _save_plan(self) -> None:
        try:
            plan = self._build_plan()
            PlanStore(self.paths).save(plan)
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(f"无法保存 TrimPlan：{exc}")
            return
        self.current_plan = plan
        self.ui.errorLabel.setText(f"TrimPlan 已安全保存：{plan.plan_id}")
        self.ui.errorLabel.show()
        self.plan_saved.emit(plan)
        if self.hook_mode:
            self.close()

    @Slot()
    def _apply_plan(self) -> None:
        try:
            plan = self._build_plan()
            PlanStore(self.paths).save(plan)
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(f"计划校验失败：{exc}")
            return
        self._set_busy(True, "正在创建派生精简任务…")
        self._write_in_progress = True
        generation = self._generation

        def apply() -> str:
            client, capabilities = connect_and_probe(request_timeout=45)
            try:
                with AuditStore(self.paths) as audit:
                    return TrimExecutor(
                        client=client,
                        inventory=InventoryService(client),
                        capabilities=capabilities,
                        audit=audit,
                    ).apply(plan)
            finally:
                client.close()

        worker = FunctionWorker(apply)
        worker.signals.result.connect(
            lambda value, current=generation: self._apply_succeeded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._apply_failed(current, message)
        )
        worker.signals.finished.connect(lambda current=generation: self._apply_finished(current))
        self.thread_pool.start(worker)

    def _apply_succeeded(self, generation: int, value: object) -> None:
        if generation != self._generation or self._closing:
            return
        thread_id = str(value)
        self.derived_created.emit(thread_id)
        QMessageBox.information(
            self,
            "派生任务已创建",
            f"新任务 ID：{thread_id}\n原任务未修改，也没有自动启动模型 turn。",
        )

    def _apply_failed(self, generation: int, message: str) -> None:
        if generation == self._generation and not self._closing:
            self._show_error(f"创建失败：{message}")

    def _apply_finished(self, generation: int) -> None:
        self._write_in_progress = False
        if generation == self._generation and not self._closing:
            self._set_busy(False)

    def _estimated_after(self) -> int:
        if self.document is None:
            return 0
        total = 0
        for turn in self.document.snapshot.turns:
            selection = self.selections.get(turn.id)
            if selection and selection.action is TrimAction.EXCLUDE:
                continue
            if selection and selection.action is TrimAction.SUMMARY:
                total += max(1, len((selection.summary or "").encode("utf-8")) // 3)
                continue
            for item in turn.items:
                item_selection = self.selections.get(item.id)
                if item_selection and item_selection.action is TrimAction.EXCLUDE:
                    continue
                if item_selection and item_selection.action is TrimAction.SUMMARY:
                    total += max(1, len((item_selection.summary or "").encode("utf-8")) // 3)
                else:
                    total += item.token_estimate
        return total

    def _update_estimate(self) -> None:
        if self.document is None:
            return
        before = self.document.snapshot.token_estimate
        after = self._estimated_after()
        saved = max(0, before - after)
        percent = round(saved * 100 / before) if before else 0
        self.ui.tokenLabel.setText(f"预计上下文：{before:,} → {after:,} tokens（节省约 {saved:,}）")
        self.ui.savingProgress.setValue(percent)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.ui.loadButton.setEnabled(not busy)
        self.ui.suggestButton.setEnabled(not busy and self.document is not None)
        self.ui.savePlanButton.setEnabled(not busy and self.document is not None)
        self.ui.applyButton.setEnabled(
            not busy
            and not self.hook_mode
            and self.document is not None
            and self.document.snapshot.status is not ThreadStatus.ACTIVE
            and self.document.capabilities.write_enabled
        )
        if message:
            self.ui.taskContextStatusLabel.setText(message)
            self.ui.taskContextStatusLabel.setToolTip(message)

    def _show_error(self, message: str) -> None:
        self.ui.errorLabel.setText("⚠ " + message)
        self.ui.errorLabel.show()

    @staticmethod
    def _target_text(target: TurnSnapshot | ThreadItemSnapshot) -> str:
        if isinstance(target, TurnSnapshot):
            return "\n".join(item.text for item in target.items if item.text)
        return target.text

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._write_in_progress:
            self._show_error("派生任务写操作正在复核；完成前不能关闭窗口。")
            event.ignore()
            return
        self._closing = True
        self._generation += 1
        self._task_generation += 1
        self.window_closed.emit()
        super().closeEvent(event)
