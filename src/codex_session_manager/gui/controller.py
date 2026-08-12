"""Controller for the Designer-authored context-trimming window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import QItemSelection, QPoint, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QTextEdit,
    QTreeWidgetItem,
)

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner
from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.gui.i18n import (
    GuiLanguage,
    action_label,
    compact_number,
    load_language,
    localized_reason,
    save_language,
    sensitive_category_label,
    thread_status_label,
)
from codex_session_manager.gui.i18n import (
    text as ui_text,
)
from codex_session_manager.gui.protocol_tags import (
    protocol_segments,
    protocol_tag_spans,
    strip_protocol_tags,
)
from codex_session_manager.gui.theme import DANGER, ON_DANGER, PANEL, PANEL_MUTED
from codex_session_manager.gui.timeline_model import TurnTimelineModel
from codex_session_manager.gui.ui_main_window import Ui_MainWindow
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import (
    ActionPlan,
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
from codex_session_manager.sensitive import (
    SensitiveScanResult,
    scan_sensitive_snapshot,
    scan_sensitive_text,
)
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


@dataclass(frozen=True, slots=True)
class TaskOperationResult:
    plan: ActionPlan
    completed_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SensitiveBatchResult:
    matches: dict[str, SensitiveScanResult]
    scanned: int
    failed: int
    cancelled: bool = False


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
        self._content_drafts: dict[str, str] = {}
        self._raw_content_view_states: dict[str, tuple[int, int, int, int]] = {}
        self._content_show_tags = False
        self._content_markdown_preview = False
        self._updating_content = False
        self._content_overlay_generation = 0
        self.current_plan: TrimPlan | None = None
        self._updating_controls = False
        self._generation = 0
        self._task_generation = 0
        self._task_selection_guard = False
        self._closing = False
        self._write_in_progress = False
        self._task_write_in_progress = False
        self._sensitive_scan_generation = 0
        self._sensitive_matches: dict[str, SensitiveScanResult] = {}
        self._sensitive_scan_complete = False
        self._task_pane_expanded = True
        self._expanded_splitter_sizes: tuple[int, ...] = (360, 430, 500, 300)
        self._language = load_language(self.paths.config_dir)
        self.ui.languageCombo.setCurrentIndex(1 if self._language is GuiLanguage.EN_US else 0)
        # Keep worker signal QObjects alive for the lifetime of the Qt
        # application, not just the review window.  The App Server request
        # can still be unwinding after a user closes this window.
        self._worker_owner = QApplication.instance() or self
        self._connect_signals()
        self._configure_views()
        self._configure_tool_rail()
        self._apply_language()
        self.ui.errorLabel.hide()
        self.ui.mainSplitter.setSizes(list(self._expanded_splitter_sizes))
        if hook_mode:
            self.ui.applyButton.hide()
            self.ui.sensitiveScanButton.hide()
            self.ui.taskPane.hide()
            self.ui.toolRail.hide()
            self.ui.taskPaneCollapseButton.hide()
            self._task_pane_expanded = False
            self.ui.cancelButton.setText(self._t("cancel_native_compact"))
            self.ui.taskContextStatusLabel.setText(self._t("hook_review"))
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
        self.ui.timelineHelp.setToolTip(self._t("timeline_usage_tooltip"))
        self.ui.timelineTitle.setToolTip(self._t("timeline_order_tooltip"))
        self.ui.contentBrowser.setLineWrapMode(self.ui.contentBrowser.LineWrapMode.WidgetWidth)
        self.ui.summaryEdit.setMinimumHeight(120)
        # Keep multi-line local suggestions readable without letting the action
        # pane consume the center workspace at the minimum window size.
        self.ui.reasonBrowser.setMinimumHeight(96)
        self.ui.reasonBrowser.setMaximumHeight(140)
        self.ui.heroLayout.setAlignment(self.ui.brandMark, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroLayout.setAlignment(self.ui.heroTextLayout, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroLayout.setAlignment(self.ui.headerBadge, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroLayout.setAlignment(self.ui.languageCombo, Qt.AlignmentFlag.AlignVCenter)
        self.ui.heroTextLayout.setSpacing(0)
        self.ui.footerMainLayout.setStretch(2, 1)
        self.ui.footerLayout.setAlignment(self.ui.footerMainLayout, Qt.AlignmentFlag.AlignVCenter)
        self.ui.footerMainLayout.setAlignment(self.ui.buttonLayout, Qt.AlignmentFlag.AlignVCenter)
        task_header = self.ui.taskListView.header()
        task_header.setStretchLastSection(False)
        task_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        task_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.ui.taskListView.setColumnWidth(0, 260)
        self.ui.taskListView.setColumnWidth(1, 72)
        self.ui.taskListView.setIndentation(14)
        self.ui.taskListView.setHeaderHidden(False)
        self.ui.contentBrowser.setAcceptRichText(False)
        self.ui.contentBrowser.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.ui.mainSplitter.setStretchFactor(0, 0)
        self.ui.mainSplitter.setStretchFactor(1, 1)
        self.ui.mainSplitter.setStretchFactor(2, 1)
        self.ui.mainSplitter.setStretchFactor(3, 0)

    def _configure_tool_rail(self) -> None:
        """Use native platform glyphs for the rail without shipping icon assets."""

        style = self.style()
        self.ui.projectTaskRailButton.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )
        self.ui.projectTaskRailButton.setIconSize(QSize(20, 20))
        self.ui.projectTaskRailButton.setFixedSize(34, 34)
        self.ui.projectTaskRailButton.setChecked(True)

    def _connect_signals(self) -> None:
        self.ui.threadIdEdit.textChanged.connect(self._filter_task_list)
        self.ui.taskListView.itemSelectionChanged.connect(self._task_selection_changed)
        self.ui.taskListView.itemClicked.connect(self._task_clicked)
        self.ui.taskListView.customContextMenuRequested.connect(self._show_task_context_menu)
        self.ui.taskRefreshButton.clicked.connect(self.load_task_list)
        self.ui.taskArchiveButton.clicked.connect(self._archive_selected_tasks)
        self.ui.taskDeleteButton.clicked.connect(self._delete_selected_tasks)
        self.ui.projectTaskRailButton.clicked.connect(self._toggle_task_pane)
        self.ui.sensitiveScanButton.toggled.connect(self._sensitive_filter_toggled)
        self.ui.taskPaneCollapseButton.clicked.connect(self._toggle_task_pane)
        self.ui.languageCombo.currentIndexChanged.connect(self._language_changed)
        self.ui.contentTagsButton.toggled.connect(self._content_tags_toggled)
        self.ui.contentMarkdownButton.toggled.connect(self._content_markdown_toggled)
        self.ui.contentBrowser.textChanged.connect(self._content_edited)
        self.ui.loadButton.clicked.connect(self._load_from_edit)
        self.ui.threadIdEdit.returnPressed.connect(self._activate_task_query)
        self.ui.actionCombo.currentIndexChanged.connect(self._action_changed)
        self.ui.summaryEdit.textChanged.connect(self._summary_changed)
        self.ui.suggestButton.clicked.connect(self._regenerate_suggestions)
        self.ui.savePlanButton.clicked.connect(self._save_plan)
        self.ui.applyButton.clicked.connect(self._apply_plan)
        self.ui.cancelButton.clicked.connect(self.close)

    def _t(self, key: str, **values: object) -> str:
        return ui_text(self._language, key, **values)

    @Slot(int)
    def _language_changed(self, index: int) -> None:
        language = GuiLanguage.EN_US if index == 1 else GuiLanguage.ZH_CN
        if language is self._language:
            return
        self._language = language
        self._apply_language()
        try:
            save_language(self.paths.config_dir, language)
        except OSError as exc:
            self._show_error(self._t("language_save_failed", error=exc))

    def _apply_language(self) -> None:
        """Retranslate the live window without rebuilding workflow state."""

        self.setWindowTitle(self._t("window_title"))
        self.ui.appSubtitleLabel.setText(self._t("subtitle"))
        self.ui.headerBadge.setText(self._t("readonly_badge"))
        self.ui.languageCombo.setToolTip(self._t("language_tooltip"))
        self.ui.languageCombo.setAccessibleName(self._t("language_tooltip"))

        self.ui.taskTitle.setText(self._t("project_tasks"))
        self.ui.projectTaskRailButton.setToolTip(self._t("project_tasks"))
        self.ui.projectTaskRailButton.setAccessibleName(self._t("project_tasks"))
        self.ui.taskPaneCollapseButton.setToolTip(self._t("collapse_tasks"))
        self.ui.taskPaneCollapseButton.setAccessibleName(self._t("collapse_tasks"))
        self.ui.taskPaneCollapseButton.setText(self._t("collapse_button"))
        self.ui.threadIdEdit.setPlaceholderText(self._t("task_search_placeholder"))
        self.ui.threadIdEdit.setAccessibleName(self._t("task_search_accessible"))
        self.ui.loadButton.setText(self._t("load_id"))
        self.ui.taskListView.setAccessibleName(self._t("task_list_accessible"))
        task_header = self.ui.taskListView.headerItem()
        task_header.setText(0, self._t("task_name"))
        task_header.setText(1, self._t("age"))
        self.ui.taskRefreshButton.setText(self._t("refresh"))
        self.ui.taskArchiveButton.setText(self._t("archive"))
        self.ui.taskDeleteButton.setText(self._t("delete"))

        self.ui.timelineTitle.setText(self._t("timeline"))
        self.ui.timelineHelp.setToolTip(self._t("timeline_usage_tooltip"))
        self.ui.timelineTitle.setToolTip(self._t("timeline_order_tooltip"))
        self.ui.contentTitle.setText(self._t("content"))
        self.ui.contentTagsButton.setText(
            self._t("hide_tags") if self._content_show_tags else self._t("show_tags")
        )
        self.ui.contentTagsButton.setToolTip(self._t("tags_tooltip"))
        self.ui.contentMarkdownButton.setText(
            self._t("markdown_exit")
            if self._content_markdown_preview
            else self._t("markdown_preview")
        )
        self.ui.contentMarkdownButton.setToolTip(self._t("markdown_tooltip"))
        self.ui.contentBrowser.setAccessibleName(self._t("content_accessible"))

        self.ui.actionTitle.setText(self._t("trim_action"))
        action_index = self.ui.actionCombo.currentIndex()
        self.ui.actionCombo.blockSignals(True)
        try:
            for index, action in ACTION_BY_INDEX.items():
                self.ui.actionCombo.setItemText(index, action_label(self._language, action))
            self.ui.actionCombo.setCurrentIndex(action_index)
        finally:
            self.ui.actionCombo.blockSignals(False)
        self.ui.reasonLabel.setText(self._t("reason"))
        self.ui.summaryLabel.setText(self._t("summary"))
        self.ui.summaryEdit.setPlaceholderText(self._t("summary_placeholder"))
        self.ui.aiConsentCheck.setText(self._t("ai_consent"))
        self.ui.aiConsentCheck.setToolTip(self._t("ai_consent_tooltip"))
        self.ui.suggestButton.setText(self._t("suggest"))

        self.ui.sensitiveScanButton.setText(self._t("sensitive_scan"))
        self.ui.sensitiveScanButton.setToolTip(self._t("sensitive_tooltip"))
        self.ui.sensitiveScanButton.setAccessibleName(self._t("sensitive_tooltip"))
        self.ui.savePlanButton.setText(self._t("save_plan"))
        self.ui.savePlanButton.setToolTip(self._t("save_plan_tooltip"))
        self.ui.applyButton.setText(self._t("apply_plan"))
        self.ui.cancelButton.setText(
            self._t("cancel_native_compact") if self.hook_mode else self._t("close")
        )
        self.ui.savingProgress.setFormat(self._t("saving_progress"))

        if self.timeline_model is not None:
            self.timeline_model.set_language(self._language)
        self._refresh_timeline_summary()
        if self.document is None:
            self.ui.taskContextStatusLabel.setText(
                self._t("hook_review") if self.hook_mode else self._t("not_loaded")
            )
            if not self.task_snapshots:
                self.ui.taskListStatusLabel.setText(self._t("task_list_not_loaded"))
            self.ui.tokenLabel.setText(self._t("estimate_empty"))
            self.ui.riskLabel.setText(self._t("risk_waiting"))
        else:
            self._refresh_loaded_context_status()
            self._update_estimate()
        if self.task_snapshots:
            self._populate_task_list(self.task_snapshots)
            if self.ui.sensitiveScanButton.isChecked() and self._sensitive_scan_complete:
                self._show_sensitive_summary()
            elif not self.ui.sensitiveScanButton.isChecked():
                self.ui.taskListStatusLabel.setText(
                    self._t("task_list_count_search", count=len(self.task_snapshots))
                )
        if self.current_target is not None:
            self._show_target(self.current_target)

    def _refresh_timeline_summary(self) -> None:
        model = self.timeline_model
        self.ui.timelineHelp.setText(
            self._t(
                "timeline_summary",
                hidden=compact_number(model.hidden_internal_item_count if model else 0),
                input=compact_number(model.input_tokens if model else 0),
                output=compact_number(model.output_tokens if model else 0),
            )
        )

    def _refresh_loaded_context_status(self) -> None:
        if self.document is None:
            return
        snapshot = self.document.snapshot
        status = self._t(
            "loaded_context",
            title=snapshot.title or snapshot.id,
            status=thread_status_label(self._language, snapshot.status),
            turns=len(snapshot.turns),
        )
        self.ui.taskContextStatusLabel.setText(status)
        self.ui.taskContextStatusLabel.setToolTip(status)

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
            self.ui.taskPaneCollapseButton.setToolTip(self._t("collapse_tasks"))
            self.ui.projectTaskRailButton.setChecked(False)
            return

        self.ui.taskPane.show()
        splitter.setSizes(list(self._expanded_splitter_sizes))
        self._task_pane_expanded = True
        self.ui.taskPaneCollapseButton.setToolTip(self._t("collapse_tasks"))
        self.ui.projectTaskRailButton.setChecked(True)

    def load_task_list(self) -> None:
        """Load lightweight task summaries without blocking the Qt thread."""

        self._task_generation += 1
        self._sensitive_scan_generation += 1
        self._sensitive_matches.clear()
        self._sensitive_scan_complete = False
        self.ui.sensitiveScanButton.blockSignals(True)
        self.ui.sensitiveScanButton.setChecked(False)
        self.ui.sensitiveScanButton.blockSignals(False)
        generation = self._task_generation
        self.ui.taskRefreshButton.setEnabled(False)
        self.ui.taskListStatusLabel.setText(self._t("task_list_loading"))

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

        worker = FunctionWorker(load, self._worker_owner)
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
            self._task_list_failed(generation, self._t("task_list_invalid"))
            return
        self.task_snapshots = value
        self._populate_task_list(value)
        self.ui.taskListStatusLabel.setText(self._t("task_list_count_search", count=len(value)))

    def _task_list_failed(self, generation: int, message: str) -> None:
        if generation != self._task_generation or self._closing:
            return
        self.ui.taskListStatusLabel.setText(self._t("task_list_failed_input"))
        self._show_error(self._t("task_list_failed", error=message))

    def _task_list_finished(self, generation: int) -> None:
        if generation == self._task_generation and not self._closing:
            self.ui.taskRefreshButton.setEnabled(True)

    @Slot(str)
    def _filter_task_list(self, _query: str) -> None:
        self._populate_task_list(self.task_snapshots)

    @Slot()
    def _task_selection_changed(self) -> None:
        if self._task_selection_guard or self._closing:
            return
        self._update_task_action_state()

    @Slot(QTreeWidgetItem, int)
    def _task_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._task_selection_guard or self._closing:
            return
        if QApplication.keyboardModifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            return
        selected_ids = self._selected_task_ids()
        if len(selected_ids) != 1:
            return
        thread_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(thread_id, str) or thread_id != selected_ids[0]:
            return
        self.load_thread(thread_id)

    def _populate_task_list(self, snapshots: tuple[ThreadSnapshot, ...]) -> None:
        query = self.ui.threadIdEdit.text().strip().casefold()
        selected_ids = set(self._selected_task_ids())
        groups: dict[str, tuple[str, list[ThreadSnapshot]]] = {}
        for snapshot in snapshots:
            if query and not self._task_matches(snapshot, query):
                continue
            if (
                self.ui.sensitiveScanButton.isChecked()
                and self._sensitive_scan_complete
                and snapshot.id not in self._sensitive_matches
            ):
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
                group = QTreeWidgetItem([group_label, ""])
                group.setToolTip(0, self._project_tooltip(members))
                group.setFirstColumnSpanned(True)
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                for snapshot in sorted(members, key=self._task_sort_key, reverse=True):
                    title = snapshot.title.strip() or self._t("unnamed_task")
                    item = QTreeWidgetItem([title, self._relative_age(snapshot)])
                    item.setData(0, Qt.ItemDataRole.UserRole, snapshot.id)
                    item.setToolTip(0, self._task_tooltip(snapshot))
                    item.setToolTip(1, self._activity_tooltip(snapshot))
                    finding = self._sensitive_matches.get(snapshot.id)
                    if finding is not None:
                        separator = "、" if self._language is GuiLanguage.ZH_CN else ", "
                        finding_summary = separator.join(
                            f"{sensitive_category_label(self._language, result.category)}×{result.count}"
                            for result in finding.findings
                        )
                        item.setIcon(
                            0,
                            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),
                        )
                        item.setToolTip(
                            0,
                            self._task_tooltip(snapshot)
                            + "\n"
                            + self._t("sensitive_finding", summary=finding_summary),
                        )
                    group.addChild(item)
                self.ui.taskListView.addTopLevelItem(group)
                group.setExpanded(True)
            for selected_id in selected_ids:
                self._select_task_in_list(selected_id, clear=False)
        finally:
            self._task_selection_guard = False
        self._update_task_action_state()

    def _select_task_in_list(self, thread_id: str, *, clear: bool = True) -> None:
        previous_guard = self._task_selection_guard
        self._task_selection_guard = True
        try:
            if clear:
                self.ui.taskListView.clearSelection()
            for group_index in range(self.ui.taskListView.topLevelItemCount()):
                group = self.ui.taskListView.topLevelItem(group_index)
                if group is None:
                    continue
                for item_index in range(group.childCount()):
                    item = group.child(item_index)
                    if item.data(0, Qt.ItemDataRole.UserRole) != thread_id:
                        continue
                    if clear or self.ui.taskListView.currentItem() is None:
                        self.ui.taskListView.setCurrentItem(item)
                    item.setSelected(True)
                    return
        finally:
            self._task_selection_guard = previous_guard
            self._update_task_action_state()

    def _selected_task_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for item in self.ui.taskListView.selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, str) and value:
                values.append(value)
        return tuple(dict.fromkeys(values))

    def _update_task_action_state(self) -> None:
        enabled = bool(self._selected_task_ids()) and not self._task_write_in_progress
        self.ui.taskArchiveButton.setEnabled(enabled)
        self.ui.taskDeleteButton.setEnabled(enabled)

    @Slot(QPoint)
    def _show_task_context_menu(self, point: QPoint) -> None:
        item = self.ui.taskListView.itemAt(point)
        if item is None:
            return
        thread_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(thread_id, str) or not thread_id:
            return
        if not item.isSelected():
            self.ui.taskListView.clearSelection()
            item.setSelected(True)
            self.ui.taskListView.setCurrentItem(item)
        selected_count = len(self._selected_task_ids())
        menu = QMenu(self)
        rename_action = menu.addAction(self._t("rename"))
        copy_action = menu.addAction(self._t("copy_id"))
        menu.addSeparator()
        archive_action = menu.addAction(self._t("archive_selected", count=selected_count))
        delete_action = menu.addAction(self._t("delete_selected", count=selected_count))
        rename_action.setEnabled(not self._task_write_in_progress)
        archive_action.setEnabled(not self._task_write_in_progress)
        delete_action.setEnabled(not self._task_write_in_progress)
        rename_action.triggered.connect(lambda _checked=False: self._rename_task(thread_id))
        copy_action.triggered.connect(lambda _checked=False: self._copy_conversation_id(thread_id))
        archive_action.triggered.connect(self._archive_selected_tasks)
        delete_action.triggered.connect(self._delete_selected_tasks)
        menu.exec(self.ui.taskListView.viewport().mapToGlobal(point))

    def _snapshot_for(self, thread_id: str) -> ThreadSnapshot | None:
        return next(
            (snapshot for snapshot in self.task_snapshots if snapshot.id == thread_id),
            None,
        )

    def _copy_conversation_id(self, thread_id: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._show_error(self._t("clipboard_unavailable"))
            return
        clipboard.setText(thread_id)
        self.ui.taskListStatusLabel.setText(self._t("id_copied"))

    def _rename_task(self, thread_id: str) -> None:
        snapshot = self._snapshot_for(thread_id)
        if snapshot is None:
            self._show_error(self._t("task_stale"))
            return
        new_name, accepted = QInputDialog.getText(
            self,
            self._t("rename_title"),
            self._t("rename_prompt"),
            QLineEdit.EchoMode.Normal,
            snapshot.title,
        )
        if not accepted:
            return
        normalized_name = new_name.strip()
        if not normalized_name:
            self._show_error(self._t("rename_empty"))
            return
        self._start_task_operation(
            self._t("rename_busy"),
            lambda: self._apply_task_rename(thread_id, normalized_name),
            self._task_rename_succeeded,
        )

    def _apply_task_rename(self, thread_id: str, new_name: str) -> TaskOperationResult:
        client, capabilities = connect_and_probe(request_timeout=45)
        try:
            inventory = InventoryService(client)
            snapshots = inventory.list(
                include_active=True,
                include_archived=True,
                include_turns=True,
            )
            plan = CleanupPlanner().plan_rename(
                snapshots,
                capabilities,
                thread_id=thread_id,
                new_name=new_name,
            )
            PlanStore(self.paths).save(plan)
            with AuditStore(self.paths) as audit:
                completed = CleanupExecutor(
                    client=client,
                    inventory=inventory,
                    capabilities=capabilities,
                    audit=audit,
                ).apply(plan)
            return TaskOperationResult(plan, completed)
        finally:
            client.close()

    def _task_rename_succeeded(self, value: object) -> None:
        if not isinstance(value, TaskOperationResult):
            self._show_error(self._t("rename_invalid"))
            return
        QMessageBox.information(
            self,
            self._t("rename_done_title"),
            self._t(
                "rename_done",
                count=len(value.completed_ids),
                plan_id=value.plan.plan_id,
            ),
        )
        self.load_task_list()

    @Slot()
    def _archive_selected_tasks(self) -> None:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            self._show_error(self._t("select_task"))
            return
        self._start_task_operation(
            self._t("archive_plan_busy"),
            lambda: self._prepare_selected_archive(selected_ids),
            self._confirm_prepared_archive,
        )

    def _prepare_selected_archive(self, selected_ids: tuple[str, ...]) -> ActionPlan:
        client, capabilities = connect_and_probe(request_timeout=45)
        try:
            snapshots = InventoryService(client).list(
                include_active=True,
                include_archived=True,
                include_turns=True,
            )
            plan = CleanupPlanner().plan_selected_archive(
                snapshots,
                capabilities,
                selected_ids,
            )
            PlanStore(self.paths).save(plan)
            return plan
        finally:
            client.close()

    def _confirm_prepared_archive(self, value: object) -> None:
        if not isinstance(value, ActionPlan):
            self._show_error(self._t("archive_plan_invalid"))
            return
        affected = {
            thread_id for target in value.targets for thread_id in target.affected_thread_ids
        }
        answer = QMessageBox.question(
            self,
            self._t("archive_confirm_title"),
            self._t(
                "archive_confirm",
                plan_id=value.plan_id,
                roots=len(value.targets),
                affected=len(affected),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.ui.taskListStatusLabel.setText(self._t("archive_saved", plan_id=value.plan_id))
            return
        self._start_task_operation(
            self._t("archive_apply_busy"),
            lambda: self._apply_prepared_archive(value),
            self._task_archive_succeeded,
        )

    def _apply_prepared_archive(self, plan: ActionPlan) -> TaskOperationResult:
        client, capabilities = connect_and_probe(request_timeout=45)
        try:
            inventory = InventoryService(client)
            with AuditStore(self.paths) as audit:
                completed = CleanupExecutor(
                    client=client,
                    inventory=inventory,
                    capabilities=capabilities,
                    audit=audit,
                ).apply(plan, confirmation=plan.plan_id)
            return TaskOperationResult(plan, completed)
        finally:
            client.close()

    def _task_archive_succeeded(self, value: object) -> None:
        if not isinstance(value, TaskOperationResult):
            self._show_error(self._t("archive_invalid"))
            return
        QMessageBox.information(
            self,
            self._t("archive_done_title"),
            self._t(
                "archive_done",
                count=len(value.completed_ids),
                plan_id=value.plan.plan_id,
            ),
        )
        self.load_task_list()

    @Slot()
    def _delete_selected_tasks(self) -> None:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            self._show_error(self._t("select_task"))
            return
        answer = QMessageBox.warning(
            self,
            self._t("purge_prepare_title"),
            self._t("purge_prepare", count=len(selected_ids)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_task_operation(
            self._t("purge_plan_busy"),
            lambda: self._prepare_selected_purge(selected_ids),
            self._confirm_prepared_purge,
        )

    def _prepare_selected_purge(self, selected_ids: tuple[str, ...]) -> ActionPlan:
        client, capabilities = connect_and_probe(request_timeout=45, experimental_api=True)
        try:
            snapshots = InventoryService(client).list(
                include_active=True,
                include_archived=True,
                include_turns=True,
            )
            with AuditStore(self.paths) as audit:
                plan = CleanupPlanner().plan_selected_purge(
                    snapshots,
                    capabilities,
                    audit,
                    selected_ids,
                )
            PlanStore(self.paths).save(plan)
            return plan
        finally:
            client.close()

    def _confirm_prepared_purge(self, value: object) -> None:
        if not isinstance(value, ActionPlan):
            self._show_error(self._t("purge_plan_invalid"))
            return
        affected_count = len(
            {thread_id for target in value.targets for thread_id in target.affected_thread_ids}
        )
        confirmation, accepted = QInputDialog.getText(
            self,
            self._t("purge_confirm_title"),
            self._t(
                "purge_confirm",
                roots=len(value.targets),
                affected=affected_count,
                plan_id=value.plan_id,
            ),
            QLineEdit.EchoMode.Normal,
        )
        if not accepted:
            self.ui.taskListStatusLabel.setText(self._t("purge_saved", plan_id=value.plan_id))
            return
        phrase, accepted = QInputDialog.getText(
            self,
            self._t("purge_final_title"),
            self._t("purge_final_prompt"),
            QLineEdit.EchoMode.Normal,
        )
        if not accepted:
            self.ui.taskListStatusLabel.setText(self._t("purge_saved", plan_id=value.plan_id))
            return
        if confirmation != value.plan_id or phrase != "PERMANENTLY DELETE CODEX TASKS":
            self._show_error(self._t("purge_mismatch"))
            return
        self._start_task_operation(
            self._t("purge_apply_busy"),
            lambda: self._apply_prepared_purge(value, confirmation, phrase),
            self._task_purge_succeeded,
        )

    def _apply_prepared_purge(
        self,
        plan: ActionPlan,
        confirmation: str,
        permanent_phrase: str,
    ) -> TaskOperationResult:
        client, capabilities = connect_and_probe(request_timeout=45, experimental_api=True)
        try:
            inventory = InventoryService(client)
            with AuditStore(self.paths) as audit:
                completed = CleanupExecutor(
                    client=client,
                    inventory=inventory,
                    capabilities=capabilities,
                    audit=audit,
                ).apply(
                    plan,
                    confirmation=confirmation,
                    permanent_phrase=permanent_phrase,
                )
            return TaskOperationResult(plan, completed)
        finally:
            client.close()

    def _task_purge_succeeded(self, value: object) -> None:
        if not isinstance(value, TaskOperationResult):
            self._show_error(self._t("purge_invalid"))
            return
        QMessageBox.information(
            self,
            self._t("purge_done_title"),
            self._t(
                "purge_done",
                count=len(value.completed_ids),
                plan_id=value.plan.plan_id,
            ),
        )
        self.load_task_list()

    def _start_task_operation(
        self,
        message: str,
        function: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> None:
        if self._task_write_in_progress:
            self._show_error(self._t("task_operation_active"))
            return
        self._task_write_in_progress = True
        self._update_task_action_state()
        self.ui.taskRefreshButton.setEnabled(False)
        self.ui.taskListStatusLabel.setText(message)
        outcome: dict[str, object] = {}
        worker = FunctionWorker(function, self._worker_owner)
        worker.signals.result.connect(lambda value: outcome.__setitem__("value", value))
        worker.signals.error.connect(lambda error: outcome.__setitem__("error", error))
        worker.signals.finished.connect(lambda: self._finish_task_operation(outcome, on_success))
        self.thread_pool.start(worker)

    def _finish_task_operation(
        self,
        outcome: dict[str, object],
        on_success: Callable[[object], None],
    ) -> None:
        self._task_write_in_progress = False
        if self._closing:
            return
        self.ui.taskRefreshButton.setEnabled(True)
        self._update_task_action_state()
        error = outcome.get("error")
        if isinstance(error, str):
            self.ui.taskListStatusLabel.setText(self._t("task_operation_not_run"))
            self._show_error(self._t("task_operation_failed", error=error))
            return
        if "value" not in outcome:
            self._show_error(self._t("task_operation_no_result"))
            return
        on_success(outcome["value"])

    @Slot(bool)
    def _sensitive_filter_toggled(self, checked: bool) -> None:
        self._sensitive_scan_generation += 1
        if self.current_target is not None:
            self._apply_content_overlays()
        if not checked:
            self._populate_task_list(self.task_snapshots)
            self.ui.taskListStatusLabel.setText(
                self._t("sensitive_off", count=len(self.task_snapshots))
            )
            return
        if self._sensitive_scan_complete:
            self._populate_task_list(self.task_snapshots)
            self._show_sensitive_summary()
            return
        if not self.task_snapshots:
            self.ui.sensitiveScanButton.blockSignals(True)
            self.ui.sensitiveScanButton.setChecked(False)
            self.ui.sensitiveScanButton.blockSignals(False)
            if self.current_target is not None:
                self._apply_content_overlays()
            self._show_error(self._t("sensitive_need_list"))
            return
        generation = self._sensitive_scan_generation
        total = len(self.task_snapshots)
        self.ui.taskListStatusLabel.setText(self._t("sensitive_progress", current=0, total=total))

        worker: FunctionWorker

        def scan() -> SensitiveBatchResult:
            client, _capabilities = connect_and_probe(request_timeout=45)
            matches: dict[str, SensitiveScanResult] = {}
            failed = 0
            scanned = 0
            try:
                inventory = InventoryService(client)
                for index, snapshot in enumerate(self.task_snapshots, start=1):
                    if generation != self._sensitive_scan_generation or self._closing:
                        return SensitiveBatchResult(matches, scanned, failed, cancelled=True)
                    try:
                        complete = inventory.read(snapshot.id, include_turns=True)
                        finding = scan_sensitive_snapshot(complete)
                    except Exception:
                        failed += 1
                    else:
                        scanned += 1
                        if finding.has_findings:
                            matches[snapshot.id] = finding
                    worker.signals.progress.emit((index, total))
                return SensitiveBatchResult(matches, scanned, failed)
            finally:
                client.close()

        worker = FunctionWorker(scan, self._worker_owner)
        worker.signals.progress.connect(
            lambda value, current=generation: self._sensitive_scan_progress(current, value)
        )
        worker.signals.result.connect(
            lambda value, current=generation: self._sensitive_scan_loaded(current, value)
        )
        worker.signals.error.connect(
            lambda error, current=generation: self._sensitive_scan_failed(current, error)
        )
        self.thread_pool.start(worker)

    def _sensitive_scan_progress(self, generation: int, value: object) -> None:
        if generation != self._sensitive_scan_generation or not isinstance(value, tuple):
            return
        if len(value) != 2 or not all(isinstance(item, int) for item in value):
            return
        current, total = value
        self.ui.taskListStatusLabel.setText(
            self._t("sensitive_progress", current=current, total=total)
        )

    def _sensitive_scan_loaded(self, generation: int, value: object) -> None:
        if (
            generation != self._sensitive_scan_generation
            or self._closing
            or not self.ui.sensitiveScanButton.isChecked()
        ):
            return
        if not isinstance(value, SensitiveBatchResult) or value.cancelled:
            return
        self._sensitive_matches = value.matches
        self._sensitive_scan_complete = True
        self._populate_task_list(self.task_snapshots)
        self._show_sensitive_summary(value.failed)

    def _sensitive_scan_failed(self, generation: int, error: str) -> None:
        if generation != self._sensitive_scan_generation or self._closing:
            return
        self._show_error(self._t("sensitive_failed", error=error))

    def _show_sensitive_summary(self, failed: int = 0) -> None:
        suffix = self._t("sensitive_read_failed", count=failed) if failed else ""
        self.ui.taskListStatusLabel.setText(
            self._t(
                "sensitive_summary",
                count=len(self._sensitive_matches),
                suffix=suffix,
            )
        )

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

    def _project_group(self, snapshot: ThreadSnapshot) -> tuple[str, str]:
        """Group worktrees and tasks by their human-facing project identity."""

        if snapshot.cwd:
            path = Path(snapshot.cwd)
            project_name = path.name or str(path)
            if snapshot.git_remote:
                remote = snapshot.git_remote.rstrip("/").removesuffix(".git")
                return f"remote:{remote.casefold()}", project_name
            # Codex worktrees have different absolute paths but share the
            # repository directory name.  The name is the useful grouping key
            # when App Server does not provide a Git remote.
            return f"project:{project_name.casefold()}", project_name
        if snapshot.git_remote:
            remote = snapshot.git_remote.rstrip("/")
            project_name = remote.rsplit("/", 1)[-1].removesuffix(".git") or remote
            return f"remote:{remote.removesuffix('.git').casefold()}", project_name
        return "__unknown_project__", self._t("unknown_project")

    @staticmethod
    def _task_sort_key(snapshot: ThreadSnapshot) -> tuple[float, str]:
        timestamp = snapshot.updated_at or snapshot.created_at
        return (timestamp.timestamp() if timestamp else 0.0, snapshot.id)

    def _status_label(self, snapshot: ThreadSnapshot) -> str:
        label = thread_status_label(self._language, snapshot.status)
        return self._t("status_archived", status=label) if snapshot.archived else label

    def _task_tooltip(self, snapshot: ThreadSnapshot) -> str:
        lines = [
            snapshot.title or self._t("unnamed_task"),
            self._t("conversation_id", thread_id=snapshot.id),
            self._t("status_line", status=self._status_label(snapshot)),
        ]
        if snapshot.cwd:
            lines.append(self._t("task_tooltip_project", cwd=snapshot.cwd))
        if snapshot.git_remote:
            lines.append(self._t("task_tooltip_git", remote=snapshot.git_remote))
        return "\n".join(lines)

    def _relative_age(self, snapshot: ThreadSnapshot) -> str:
        timestamp = snapshot.updated_at or snapshot.created_at
        if timestamp is None:
            return self._t("unknown")
        elapsed_seconds = max(0, (datetime.now(UTC) - timestamp).total_seconds())
        days = int(elapsed_seconds // 86_400)
        return self._t("today") if days == 0 else self._t("days_ago", days=days)

    def _activity_tooltip(self, snapshot: ThreadSnapshot) -> str:
        timestamp = snapshot.updated_at or snapshot.created_at
        if timestamp is None:
            return self._t("no_activity")
        return self._t(
            "last_activity",
            timestamp=timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            thread_id=snapshot.id,
        )

    def _project_tooltip(self, snapshots: list[ThreadSnapshot]) -> str:
        paths = sorted({snapshot.cwd for snapshot in snapshots if snapshot.cwd})
        remotes = sorted({snapshot.git_remote for snapshot in snapshots if snapshot.git_remote})
        lines = [self._t("task_count", count=len(snapshots))]
        if paths:
            lines.append(self._t("project_paths", paths="；".join(paths)))
        if remotes:
            lines.append(self._t("git_remotes", remotes="；".join(remotes)))
        return "\n".join(lines) if len(lines) > 1 else self._t("no_project_mapping")

    @Slot()
    def _activate_task_query(self) -> None:
        query = self.ui.threadIdEdit.text().strip()
        if not query:
            return
        if any(snapshot.id == query for snapshot in self.task_snapshots):
            self.load_thread(query)
            return
        self.ui.taskListStatusLabel.setText(self._t("query_filtered"))

    @Slot()
    def _load_from_edit(self) -> None:
        thread_id = self.ui.threadIdEdit.text().strip()
        if not thread_id:
            self._show_error(self._t("enter_conversation_id"))
            return
        self.load_thread(thread_id)

    def load_thread(self, thread_id: str) -> None:
        self._generation += 1
        generation = self._generation
        self._set_busy(True, self._t("thread_loading"))

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

        worker = FunctionWorker(load, self._worker_owner)
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
            self._show_error(self._t("load_invalid"))
            return
        self.document = value
        self.selections = {
            selection.target_id: selection for selection in value.suggested_plan.selections
        }
        self.current_plan = value.suggested_plan
        self.timeline_model = TurnTimelineModel(
            value.snapshot,
            self.selections,
            self,
            language=self._language,
        )
        self.ui.timelineView.setModel(self.timeline_model)
        self._configure_views()
        self.ui.timelineView.expandToDepth(0)
        self.ui.timelineView.selectionModel().selectionChanged.connect(self._selection_changed)
        self._refresh_loaded_context_status()
        self._refresh_timeline_summary()
        self._select_task_in_list(value.snapshot.id)
        self.ui.savePlanButton.setEnabled(not self.hook_mode or value.capabilities.write_enabled)
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
                self._t(
                    "read_only_server",
                    reason=value.capabilities.read_only_reason or self._t("unknown_protocol"),
                )
            )

    def _load_failed(self, generation: int, message: str) -> None:
        if generation != self._generation or self._closing:
            return
        self._show_error(self._t("load_failed", error=message))

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
        self.current_target = target
        self._updating_controls = True
        try:
            if isinstance(target, TurnSnapshot):
                text = "\n\n".join(item.text for item in target.items if item.text)
            else:
                text = target.text
            protected = self._target_protected_reasons(target)
            if len(text) > MAX_PREVIEW_CHARS:
                half = MAX_PREVIEW_CHARS // 2
                text = text[:half] + "\n\n" + self._t("preview_truncated") + "\n\n" + text[-half:]
            self._content_drafts.setdefault(target.id, text)
            self._render_content()
            selection = self.selections.get(target.id)
            action = selection.action if selection else TrimAction.KEEP
            self.ui.actionCombo.setCurrentIndex(INDEX_BY_ACTION[action])
            self.ui.summaryEdit.setPlainText(selection.summary or "" if selection else "")
            self.ui.summaryEdit.setEnabled(action is TrimAction.SUMMARY)
            self.ui.reasonBrowser.setPlainText(
                localized_reason(self._language, selection.reason)
                if selection
                else self._t("inherited_action")
            )
            if protected:
                self.ui.riskLabel.setText(
                    self._t(
                        "risk_protected",
                        reasons="；".join(
                            localized_reason(self._language, reason) for reason in protected
                        ),
                    )
                )
            else:
                self.ui.riskLabel.setText(self._t("risk_review"))
        finally:
            self._updating_controls = False

    def _render_content(
        self,
        *,
        view_state: tuple[int, int, int, int] | None = None,
    ) -> None:
        """Render the local content draft in raw or Markdown preview mode."""

        target = self.current_target
        if target is None:
            return
        raw_text = self._content_drafts.get(target.id, self._target_text(target))
        self._content_overlay_generation += 1
        self._updating_content = True
        try:
            self.ui.contentBrowser.blockSignals(True)
            # Drop cursors that belong to the previous document before clear()
            # replaces its contents.  This keeps repeated target switches safe
            # in both the interpreter and the standalone/Nuitka bundle.
            self.ui.contentBrowser.setExtraSelections([])
            self.ui.contentBrowser.clear()
            protected = bool(self._target_protected_reasons(target))
            self.ui.contentBrowser.setReadOnly(self._content_markdown_preview or protected)
            self.ui.contentBrowser.setToolTip(
                self._t("protected_edit_tooltip") if protected else ""
            )
            self.ui.contentBrowser.setPlaceholderText(self._t("content_empty"))
            if self._content_markdown_preview:
                preview_text = raw_text
                if self._content_show_tags:
                    # Markdown treats angle-bracketed protocol tags as HTML;
                    # escape them so the explicit “显示标签” mode is literal.
                    preview_text = preview_text.replace("<", "&lt;").replace(">", "&gt;")
                else:
                    preview_text = strip_protocol_tags(preview_text)
                self.ui.contentBrowser.setMarkdown(preview_text)
                self._apply_content_overlays()
            else:
                self.ui.contentBrowser.setPlainText(raw_text)
                self._apply_content_overlays()
            if view_state is None:
                self.ui.contentBrowser.moveCursor(QTextCursor.MoveOperation.Start)
            else:
                self._restore_content_view_state(view_state)
        finally:
            self.ui.contentBrowser.blockSignals(False)
            self._updating_content = False

    def _apply_content_overlays(self) -> None:
        """Apply view-only tag/segment styling without mutating document text."""

        text = self.ui.contentBrowser.toPlainText()
        document = self.ui.contentBrowser.document()
        segments = () if self._content_markdown_preview else protocol_segments(text)
        tag_spans = () if self._content_markdown_preview else protocol_tag_spans(text)
        extra_selections: list[QTextEdit.ExtraSelection] = []

        def add_selection(
            start: int,
            end: int,
            *,
            background: str,
            foreground: str | None = None,
            full_width: bool = False,
            collapsed: bool = False,
        ) -> None:
            if end <= start:
                return
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            char_format = QTextCharFormat()
            char_format.setBackground(QColor(background))
            if foreground is not None:
                char_format.setForeground(QColor(foreground))
            if full_width:
                char_format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            if collapsed:
                char_format.setFontPointSize(1.0)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = char_format
            extra_selections.append(selection)

        # White is the base content surface; the alternate band is deliberately
        # near-white so long source blocks remain easy to read.
        if not self._content_markdown_preview:
            for segment_index, (start, end) in enumerate(segments):
                add_selection(
                    start,
                    end,
                    background=PANEL if segment_index % 2 == 0 else PANEL_MUTED,
                    full_width=True,
                )

        if self.ui.sensitiveScanButton.isChecked():
            highlighted_ranges: list[tuple[int, int]] = []
            for sensitive_span in scan_sensitive_text(text).spans:
                if highlighted_ranges and sensitive_span.start <= highlighted_ranges[-1][1]:
                    previous_start, previous_end = highlighted_ranges[-1]
                    highlighted_ranges[-1] = (
                        previous_start,
                        max(previous_end, sensitive_span.end),
                    )
                else:
                    highlighted_ranges.append((sensitive_span.start, sensitive_span.end))
            for start, end in highlighted_ranges:
                add_selection(
                    start,
                    end,
                    background=DANGER,
                    foreground=ON_DANGER,
                )

        if not self._content_markdown_preview and not self._content_show_tags and segments:
            segment_index = 0
            for tag_span in tag_spans:
                while (
                    segment_index + 1 < len(segments)
                    and tag_span.start >= segments[segment_index][1]
                ):
                    segment_index += 1
                background = PANEL if segment_index % 2 == 0 else PANEL_MUTED
                # Match the segment background while making protocol markup
                # invisible; this also works on alternating rows.
                add_selection(
                    tag_span.start,
                    tag_span.end,
                    background=background,
                    foreground=background,
                    collapsed=True,
                )
        self.ui.contentBrowser.setExtraSelections(extra_selections)

    @Slot(bool)
    def _content_tags_toggled(self, checked: bool) -> None:
        view_state = self._capture_content_view_state()
        self._content_show_tags = checked
        self.ui.contentTagsButton.setText(self._t("hide_tags") if checked else self._t("show_tags"))
        self._render_content(view_state=view_state)

    @Slot(bool)
    def _content_markdown_toggled(self, checked: bool) -> None:
        target_id = self.current_target.id if self.current_target is not None else None
        current_state = self._capture_content_view_state()
        if checked and target_id is not None:
            self._raw_content_view_states[target_id] = current_state
        self._content_markdown_preview = checked
        self.ui.contentMarkdownButton.setText(
            self._t("markdown_exit") if checked else self._t("markdown_preview")
        )
        view_state = (
            self._raw_content_view_states.get(target_id, current_state)
            if not checked and target_id is not None
            else current_state
        )
        self._render_content(view_state=view_state)

    def _capture_content_view_state(self) -> tuple[int, int, int, int]:
        cursor = self.ui.contentBrowser.textCursor()
        return (
            cursor.position(),
            cursor.anchor(),
            self.ui.contentBrowser.verticalScrollBar().value(),
            self.ui.contentBrowser.horizontalScrollBar().value(),
        )

    def _restore_content_view_state(self, state: tuple[int, int, int, int]) -> None:
        position, anchor, vertical, horizontal = state
        maximum = max(0, self.ui.contentBrowser.document().characterCount() - 1)
        cursor = QTextCursor(self.ui.contentBrowser.document())
        cursor.setPosition(min(maximum, max(0, anchor)))
        cursor.setPosition(
            min(maximum, max(0, position)),
            QTextCursor.MoveMode.KeepAnchor,
        )
        self.ui.contentBrowser.setTextCursor(cursor)
        self.ui.contentBrowser.verticalScrollBar().setValue(vertical)
        self.ui.contentBrowser.horizontalScrollBar().setValue(horizontal)

    @Slot()
    def _content_edited(self) -> None:
        if self._updating_content or self._content_markdown_preview or self.current_target is None:
            return
        if self._target_protected_reasons(self.current_target):
            return
        text = self.ui.contentBrowser.toPlainText()
        self._content_drafts[self.current_target.id] = text
        selection = self.selections.get(self.current_target.id)
        if text.strip():
            self._normalize_selection_scope(self.current_target)
            if selection is not None and selection.action is TrimAction.SUMMARY:
                selection = selection.model_copy(update={"summary": text})
            else:
                selection = TrimSelection(
                    target_id=self.current_target.id,
                    target_level=(
                        "turn" if isinstance(self.current_target, TurnSnapshot) else "item"
                    ),
                    action=TrimAction.SUMMARY,
                    summary=text,
                    reason=self._t("edited_summary_reason"),
                    suggested=False,
                )
            self.selections[self.current_target.id] = selection
            self._updating_controls = True
            try:
                self.ui.actionCombo.setCurrentIndex(INDEX_BY_ACTION[TrimAction.SUMMARY])
                self.ui.summaryEdit.setPlainText(text)
                self.ui.summaryEdit.setEnabled(True)
                self.ui.reasonBrowser.setPlainText(selection.reason)
            finally:
                self._updating_controls = False
            if self.timeline_model:
                self.timeline_model.refresh_actions()
            self._update_estimate()
        self._content_overlay_generation += 1
        generation = self._content_overlay_generation
        target_id = self.current_target.id
        QTimer.singleShot(
            0,
            lambda: self._apply_scheduled_content_overlays(generation, target_id),
        )

    def _apply_scheduled_content_overlays(self, generation: int, target_id: str) -> None:
        if (
            generation != self._content_overlay_generation
            or self._closing
            or self.current_target is None
            or self.current_target.id != target_id
        ):
            return
        self._apply_content_overlays()

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
            self._show_error(self._t("hard_protected_action"))
            self._show_target(self.current_target)
            return
        self._normalize_selection_scope(self.current_target)
        existing = self.selections.get(self.current_target.id)
        summary = self.ui.summaryEdit.toPlainText().strip() or None
        if action is TrimAction.SUMMARY and not summary:
            summary = self._content_drafts.get(
                self.current_target.id, self._target_text(self.current_target)
            )[:1200] or self._t("summary_fingerprint")
        self.selections[self.current_target.id] = TrimSelection(
            target_id=self.current_target.id,
            target_level="turn" if isinstance(self.current_target, TurnSnapshot) else "item",
            action=action,
            summary=summary if action is TrimAction.SUMMARY else None,
            reason=existing.reason if existing else self._t("manual_reason"),
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
        else:
            self._content_drafts[self.current_target.id] = self._target_text(self.current_target)
            self._render_content()
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
            self._show_error(self._t("ai_not_configured"))
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
            self._show_error(self._t("plan_save_failed", error=exc))
            return
        self.current_plan = plan
        self.ui.errorLabel.setText(self._t("plan_saved", plan_id=plan.plan_id))
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
            self._show_error(self._t("plan_validate_failed", error=exc))
            return
        self._set_busy(True, self._t("apply_busy"))
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

        worker = FunctionWorker(apply, self._worker_owner)
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
            self._t("derived_title"),
            self._t("derived_message", thread_id=thread_id),
        )

    def _apply_failed(self, generation: int, message: str) -> None:
        if generation == self._generation and not self._closing:
            self._show_error(self._t("apply_failed", error=message))

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
        self.ui.tokenLabel.setText(
            self._t(
                "estimate",
                before=f"{before:,}",
                after=f"{after:,}",
                saved=f"{saved:,}",
            )
        )
        self.ui.savingProgress.setValue(percent)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.ui.loadButton.setEnabled(not busy)
        self.ui.suggestButton.setEnabled(not busy and self.document is not None)
        self.ui.savePlanButton.setEnabled(
            not busy
            and self.document is not None
            and (not self.hook_mode or self.document.capabilities.write_enabled)
        )
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

    def _normalize_selection_scope(
        self,
        target: TurnSnapshot | ThreadItemSnapshot,
    ) -> None:
        """Keep turn- and item-level actions unambiguous before sealing a plan."""

        if isinstance(target, TurnSnapshot):
            for item in target.items:
                self.selections.pop(item.id, None)
            return
        if self.document is None:
            return
        parent = next(
            (
                turn
                for turn in self.document.snapshot.turns
                if any(item.id == target.id for item in turn.items)
            ),
            None,
        )
        if parent is None:
            return
        parent_selection = self.selections.get(parent.id)
        if parent_selection is None or parent_selection.action is TrimAction.KEEP:
            return
        self.selections[parent.id] = TrimSelection(
            target_id=parent.id,
            target_level="turn",
            action=TrimAction.KEEP,
            reason=self._t("manual_reason"),
            suggested=False,
        )

    @staticmethod
    def _target_protected_reasons(
        target: TurnSnapshot | ThreadItemSnapshot,
    ) -> tuple[str, ...]:
        if isinstance(target, TurnSnapshot):
            return tuple(
                dict.fromkeys(reason for item in target.items for reason in item.protected_reasons)
            )
        return target.protected_reasons

    @staticmethod
    def _target_text(target: TurnSnapshot | ThreadItemSnapshot) -> str:
        if isinstance(target, TurnSnapshot):
            return "\n".join(item.text for item in target.items if item.text)
        return target.text

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._write_in_progress or self._task_write_in_progress:
            self._show_error(self._t("write_in_progress"))
            event.ignore()
            return
        self._closing = True
        self._generation += 1
        self._task_generation += 1
        self._sensitive_scan_generation += 1
        self._content_overlay_generation += 1
        self.window_closed.emit()
        super().closeEvent(event)
