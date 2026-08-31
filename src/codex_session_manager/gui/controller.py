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
    QButtonGroup,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QStyle,
    QTextEdit,
    QTreeWidgetItem,
)

from codex_session_manager.cleanup_review import prepare_cleanup_action_plan
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
from codex_session_manager.gui.memory_segment_model import MemorySegmentModel
from codex_session_manager.gui.protocol_tags import (
    protocol_segments,
    protocol_tag_spans,
    strip_protocol_tags,
)
from codex_session_manager.gui.review_mode import ReviewMode
from codex_session_manager.gui.review_state import (
    ReviewState,
    protected_reasons,
    target_text,
)
from codex_session_manager.gui.theme import DANGER, ON_DANGER, PANEL, PANEL_MUTED
from codex_session_manager.gui.timeline_model import TurnTimelineModel
from codex_session_manager.gui.ui_main_window import Ui_MainWindow
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.memory import (
    MemoryAction,
    MemoryApplyResult,
    MemoryPlan,
    MemorySegment,
    MemorySelection,
    MemoryService,
    MemorySnapshot,
    memory_unified_diff,
    render_memory,
)
from codex_session_manager.models import (
    SAFE_INACTIVE_STATUSES,
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
from codex_session_manager.pending_plans import (
    PendingPlanStatus,
    PendingTrimPlan,
    PendingTrimPlanStore,
)
from codex_session_manager.pending_service import PendingPlanService
from codex_session_manager.plans import PlanStore
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    SuggestedAction,
    SuggestionBundle,
    SuggestionBundleStore,
    SuggestionTarget,
    codex_account_fingerprint,
)
from codex_session_manager.sensitive import (
    SensitiveScanResult,
    scan_sensitive_text,
)
from codex_session_manager.suggestions import ExternalSuggestionBundleProvider
from codex_session_manager.trim import (
    LocalTrimSuggester,
    TrimError,
    validate_selections,
)
from codex_session_manager.workflows import (
    ActionExecutionResult,
    ApplicationWorkflows,
    BackupArchiveResult,
    BackupCreationResult,
    CleanupCandidateInventory,
    SensitiveScanBatch,
)

ACTION_BY_INDEX = {
    0: TrimAction.KEEP,
    1: TrimAction.EXCLUDE,
    2: TrimAction.SUMMARY,
    3: TrimAction.PROTECT,
}
INDEX_BY_ACTION = {value: key for key, value in ACTION_BY_INDEX.items()}
MEMORY_ACTION_BY_INDEX = {
    0: MemoryAction.KEEP,
    1: MemoryAction.DELETE,
    2: MemoryAction.REPLACE,
    3: MemoryAction.PROTECT,
}
INDEX_BY_MEMORY_ACTION = {value: key for key, value in MEMORY_ACTION_BY_INDEX.items()}
MAX_PREVIEW_CHARS = 200_000


@dataclass(frozen=True, slots=True)
class ReviewDocument:
    snapshot: ThreadSnapshot
    capabilities: CapabilityMatrix
    suggested_plan: TrimPlan
    external_applied_target_ids: tuple[str, ...] = ()
    external_ignored_target_ids: tuple[str, ...] = ()


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
        mode: ReviewMode = ReviewMode.CONTEXT_TRIM,
        workflows: ApplicationWorkflows | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)  # type: ignore[no-untyped-call]
        self.paths = paths or get_paths()
        self.paths.ensure()
        self.workflows = workflows or ApplicationWorkflows(paths=self.paths)
        self.trigger = trigger
        self.source_turn_id = source_turn_id
        self.hook_mode = hook_mode
        self.review_mode = mode
        self._project_review_mode = (
            mode if mode is not ReviewMode.MEMORY_EDIT else ReviewMode.CONTEXT_TRIM
        )
        self.review_request: ReviewRequest | None = None
        self.review_bundle: SuggestionBundle | None = None
        self._cleanup_candidate_ids: tuple[str, ...] = ()
        self._cleanup_loaded_candidate_ids: tuple[str, ...] = ()
        self._cleanup_loaded_selection_pending: str | None = None
        self._supplemental_candidate_ids: tuple[str, ...] = ()
        self._purge_candidate_ids: tuple[str, ...] = ()
        self._cleanup_suggestions: dict[str, SuggestionTarget] = {}
        self._cleanup_initial_selection_pending = False
        self._memory_paths: tuple[str, ...] = ()
        self.memory_service = MemoryService(self.paths)
        self.memory_snapshot: MemorySnapshot | None = None
        self.memory_selections: dict[str, MemorySelection] = {}
        self.memory_timeline_model: MemorySegmentModel | None = None
        self.current_memory_segment: MemorySegment | None = None
        self.current_memory_plan: MemoryPlan | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self.document: ReviewDocument | None = None
        self.timeline_model: TurnTimelineModel | None = None
        self.task_snapshots: tuple[ThreadSnapshot, ...] = ()
        self._all_task_snapshots: tuple[ThreadSnapshot, ...] = ()
        self._verified_backup_ids: frozenset[str] = frozenset()
        self.selections: dict[str, TrimSelection] = {}
        self.review_state: ReviewState | None = None
        self.current_target: TurnSnapshot | ThreadItemSnapshot | None = None
        self._content_drafts: dict[str, str] = {}
        self._raw_content_view_states: dict[str, tuple[int, int, int, int]] = {}
        self._content_show_tags = False
        self._content_markdown_preview = False
        self._updating_content = False
        self._content_overlay_generation = 0
        self.current_plan: TrimPlan | None = None
        self.pending_trim_plan: PendingTrimPlan | None = None
        self._pending_plan_override: TrimPlan | None = None
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
        self._sensitive_progress_dialog: QProgressDialog | None = None
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
        self._apply_review_mode()
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
        elif load_task_list and mode is not ReviewMode.MEMORY_EDIT:
            self.load_task_list()
        elif mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
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
        self.ui.memoryRailButton.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.ui.memoryRailButton.setIconSize(QSize(20, 20))
        self.ui.memoryRailButton.setFixedSize(34, 34)
        self._rail_mode_group = QButtonGroup(self)
        self._rail_mode_group.setExclusive(True)
        self._rail_mode_group.addButton(self.ui.projectTaskRailButton)
        self._rail_mode_group.addButton(self.ui.memoryRailButton)

    def _connect_signals(self) -> None:
        self.ui.threadIdEdit.textChanged.connect(self._filter_task_list)
        self.ui.taskListView.itemSelectionChanged.connect(self._task_selection_changed)
        self.ui.taskListView.itemClicked.connect(self._task_clicked)
        self.ui.taskListView.customContextMenuRequested.connect(self._show_task_context_menu)
        self.ui.taskRefreshButton.clicked.connect(self.load_task_list)
        self.ui.taskBackupButton.clicked.connect(self._task_backup_clicked)
        self.ui.taskArchiveButton.clicked.connect(self._archive_selected_tasks)
        self.ui.taskDeleteButton.clicked.connect(self._delete_selected_tasks)
        self.ui.projectTaskRailButton.clicked.connect(self._project_rail_clicked)
        self.ui.memoryRailButton.clicked.connect(self._memory_rail_clicked)
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
        self.ui.memoryRailButton.setToolTip(self._t("memory_window_title"))
        self.ui.memoryRailButton.setAccessibleName(self._t("memory_window_title"))
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
        self.ui.taskBackupButton.setText(self._t("backup"))
        self.ui.taskBackupButton.setToolTip(self._t("backup_selected", count=1))
        self.ui.taskBackupButton.setAccessibleName(self._t("backup"))
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
        if self._sensitive_progress_dialog is not None:
            current = max(0, self._sensitive_progress_dialog.value())
            total = self._sensitive_progress_dialog.maximum()
            self._sensitive_progress_dialog.setWindowTitle(self._t("sensitive_progress_title"))
            self._sensitive_progress_dialog.setCancelButtonText(
                self._t("sensitive_progress_cancel")
            )
            self._sensitive_progress_dialog.setLabelText(
                self._t("sensitive_progress", current=current, total=total)
            )
        self.ui.savePlanButton.setText(self._t("save_plan"))
        self.ui.savePlanButton.setToolTip(self._t("save_plan_tooltip"))
        self.ui.applyButton.setText(self._t("apply_plan"))
        self.ui.cancelButton.setText(
            self._t("cancel_native_compact") if self.hook_mode else self._t("close")
        )
        self.ui.savingProgress.setFormat(self._t("saving_progress"))

        if self.timeline_model is not None:
            self.timeline_model.set_language(self._language)
        if self.memory_timeline_model is not None:
            self.memory_timeline_model.set_language(self._language)
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
        self._apply_review_mode()
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()

    def set_review_mode(self, mode: ReviewMode, *, refresh: bool = True) -> None:
        """Switch the existing Designer window between related review workflows."""

        if self.hook_mode and mode is not ReviewMode.CONTEXT_TRIM:
            raise ValueError("Hook review only supports context trimming")
        if mode is not ReviewMode.MEMORY_EDIT:
            self._project_review_mode = mode
        self.review_mode = mode
        self._apply_review_mode()
        if mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
            return
        if not refresh:
            return
        if self.task_snapshots:
            self._populate_task_list(self.task_snapshots)
        else:
            self.load_task_list()

    def load_review_request(self, request: ReviewRequest) -> None:
        """Inject a sealed LLM/Skill request into the existing review window."""

        request.verify()
        if request.account_root_fingerprint != codex_account_fingerprint(self.paths):
            raise ValueError("review request is bound to another Codex account root")
        bundle: SuggestionBundle | None = None
        if request.suggestion_bundle_path:
            bundle = SuggestionBundleStore(self.paths).load(Path(request.suggestion_bundle_path))
            if bundle.operation is not request.operation:
                raise ValueError("suggestion bundle operation does not match review request")
        self.review_request = request
        self.review_bundle = bundle
        self.setProperty("csmReviewRequestId", request.request_id)
        self.setProperty("csmReviewOperation", request.operation.value)

        if request.operation is ReviewOperation.CONVERSATION_CLEANUP:
            self._cleanup_candidate_ids = request.target_ids
            self._cleanup_loaded_candidate_ids = ()
            self._cleanup_loaded_selection_pending = None
            self._supplemental_candidate_ids = ()
            self._purge_candidate_ids = ()
            self._cleanup_suggestions = {
                target.target_id: target
                for target in (bundle.targets if bundle is not None else ())
                if target.target_id is not None
            }
            self._cleanup_initial_selection_pending = True
            self.set_review_mode(ReviewMode.CONVERSATION_CLEANUP, refresh=False)
            self.load_task_list()
            return
        if request.operation is ReviewOperation.CONTEXT_TRIM:
            self._cleanup_candidate_ids = ()
            self._cleanup_loaded_candidate_ids = ()
            self._cleanup_loaded_selection_pending = None
            self._supplemental_candidate_ids = ()
            self._purge_candidate_ids = ()
            self._cleanup_suggestions.clear()
            self.set_review_mode(ReviewMode.CONTEXT_TRIM, refresh=False)
            thread_id = request.target_ids[0]
            self.ui.threadIdEdit.setText(thread_id)
            self.load_thread(thread_id)
            return
        if request.operation is ReviewOperation.MEMORY_EDIT:
            self._memory_paths = request.target_paths
            self.set_review_mode(ReviewMode.MEMORY_EDIT, refresh=False)
            self._populate_memory_sources()
            return
        raise ValueError(
            f"review operation is not supported by the main review GUI: {request.operation}"
        )

    def load_pending_trim_plan(self, pending: PendingTrimPlan) -> None:
        """Load one READY Hook plan into the original context-review GUI."""

        store = PendingTrimPlanStore(self.paths)
        stored = store.load(store.path_for(pending.plan_id))
        if stored != pending:
            raise ValueError("pending TrimPlan changed before opening review")
        if stored.status is not PendingPlanStatus.READY:
            raise ValueError("pending TrimPlan must be READY before review")
        plan_path = Path(stored.plan_path)
        plans_root = self.paths.plans_dir.resolve(strict=True)
        if plan_path.is_symlink() or plan_path.resolve(strict=True).parent != plans_root:
            raise ValueError("pending TrimPlan escaped the private plans directory")
        plan = PlanStore(self.paths).load_trim(plan_path)
        if plan.plan_id != stored.plan_id or plan.plan_sha256 != stored.plan_sha256:
            raise ValueError("pending TrimPlan identity binding mismatch")
        self.pending_trim_plan = stored
        self._pending_plan_override = plan
        self.trigger = plan.trigger
        self.source_turn_id = plan.source_turn_id
        self.setProperty("csmPendingTrimPlanId", plan.plan_id)
        self.set_review_mode(ReviewMode.CONTEXT_TRIM, refresh=False)
        self.ui.threadIdEdit.setText(plan.source_thread_id)
        self.load_thread(plan.source_thread_id)

    def _apply_review_mode(self) -> None:
        """Apply mode-specific labels and visibility without rebuilding widgets."""

        context_mode = self.review_mode is ReviewMode.CONTEXT_TRIM
        cleanup_mode = self.review_mode is ReviewMode.CONVERSATION_CLEANUP
        memory_mode = self.review_mode is ReviewMode.MEMORY_EDIT

        self.ui.projectTaskRailButton.blockSignals(True)
        self.ui.memoryRailButton.blockSignals(True)
        try:
            self.ui.projectTaskRailButton.setChecked(not memory_mode)
            self.ui.memoryRailButton.setChecked(memory_mode)
        finally:
            self.ui.projectTaskRailButton.blockSignals(False)
            self.ui.memoryRailButton.blockSignals(False)

        self.ui.taskPane.show()
        if not self._task_pane_expanded:
            self.ui.mainSplitter.setSizes(list(self._expanded_splitter_sizes))
            self._task_pane_expanded = True
        self.ui.taskDeleteButton.setVisible(context_mode)
        self.ui.taskRefreshButton.setVisible(not memory_mode)
        self.ui.taskBackupButton.setVisible(not memory_mode)
        self.ui.taskArchiveButton.setVisible(context_mode)
        self.ui.sensitiveScanButton.setVisible(not memory_mode)
        self.ui.loadButton.setVisible(not memory_mode)
        self.ui.contentTagsButton.setVisible(not memory_mode)
        self.ui.contentMarkdownButton.setVisible(not memory_mode)
        self.ui.actionCombo.setVisible(not cleanup_mode)
        self.ui.actionCombo.setEnabled(context_mode or memory_mode)
        self.ui.summaryLabel.setVisible(not cleanup_mode)
        self.ui.summaryEdit.setVisible(not cleanup_mode)
        self.ui.summaryEdit.setEnabled(
            (context_mode or memory_mode) and self.ui.actionCombo.currentIndex() == 2
        )
        self.ui.aiConsentCheck.setVisible(context_mode)
        self.ui.suggestButton.setVisible(context_mode)
        self.ui.savePlanButton.setVisible(context_mode or memory_mode)
        self.ui.applyButton.setVisible((context_mode or memory_mode) and not self.hook_mode)
        self.ui.savingProgress.setVisible(context_mode)
        self.ui.tokenLabel.setVisible(context_mode)
        if memory_mode:
            self.ui.timelineView.setModel(self.memory_timeline_model)
        elif self.timeline_model is not None:
            self.ui.timelineView.setModel(self.timeline_model)

        if context_mode:
            self.setWindowTitle(self._t("window_title"))
            self.ui.appSubtitleLabel.setText(self._t("subtitle"))
            self.ui.headerBadge.setText(self._t("readonly_badge"))
            self.ui.taskTitle.setText(self._t("project_tasks"))
            self.ui.timelineTitle.setText(self._t("timeline"))
            self.ui.contentTitle.setText(self._t("content"))
            self.ui.actionTitle.setText(self._t("trim_action"))
            self.ui.taskBackupButton.setText(self._t("backup"))
            self.ui.taskBackupButton.setToolTip(self._t("backup_selected", count=1))
            self.ui.taskArchiveButton.setText(self._t("archive"))
            self.ui.threadIdEdit.setPlaceholderText(self._t("task_search_placeholder"))
            task_header = self.ui.taskListView.headerItem()
            task_header.setText(0, self._t("task_name"))
            task_header.setText(1, self._t("age"))
            for index, action in ACTION_BY_INDEX.items():
                self.ui.actionCombo.setItemText(index, action_label(self._language, action))
            if self.current_target is not None:
                self._show_target(self.current_target)
            return

        if cleanup_mode:
            self.setWindowTitle(self._t("cleanup_window_title"))
            self.ui.appSubtitleLabel.setText(self._t("cleanup_subtitle"))
            self.ui.headerBadge.setText(self._t("cleanup_badge"))
            self.ui.taskTitle.setText(self._t("cleanup_candidates"))
            self.ui.timelineTitle.setText(self._t("cleanup_timeline"))
            self.ui.contentTitle.setText(self._t("cleanup_content"))
            self.ui.actionTitle.setText(self._t("cleanup_suggestion"))
            self.ui.taskBackupButton.setText(self._t("cleanup_backup_archive"))
            self.ui.taskBackupButton.setToolTip(self._t("cleanup_backup_archive_selected", count=1))
            self.ui.threadIdEdit.setPlaceholderText(self._t("cleanup_search_placeholder"))
            task_header = self.ui.taskListView.headerItem()
            task_header.setText(0, self._t("cleanup_candidate"))
            task_header.setText(1, self._t("age"))
            if self.document is None:
                self.ui.taskContextStatusLabel.setText(self._t("cleanup_waiting"))
            if self.current_target is not None:
                self._show_target(self.current_target)
            return

        self.setWindowTitle(self._t("memory_window_title"))
        self.ui.appSubtitleLabel.setText(self._t("memory_subtitle"))
        self.ui.headerBadge.setText(self._t("memory_badge"))
        self.ui.taskTitle.setText(self._t("memory_sources"))
        self.ui.timelineTitle.setText(self._t("memory_segments"))
        self.ui.contentTitle.setText(self._t("memory_content"))
        self.ui.actionTitle.setText(self._t("memory_action"))
        self.ui.threadIdEdit.setPlaceholderText(self._t("memory_search_placeholder"))
        task_header = self.ui.taskListView.headerItem()
        task_header.setText(0, self._t("memory_source"))
        task_header.setText(1, self._t("memory_status"))
        for index, key in enumerate(
            ("memory_keep", "memory_delete", "memory_replace", "memory_protect")
        ):
            self.ui.actionCombo.setItemText(index, self._t(key))
        self.ui.summaryLabel.setText(self._t("memory_replacement"))
        self.ui.savePlanButton.setText(self._t("memory_save_plan"))
        self.ui.applyButton.setText(self._t("memory_apply_plan"))
        self.ui.contentBrowser.setReadOnly(True)
        if self.memory_snapshot is None:
            self.ui.reasonBrowser.setPlainText(self._t("memory_waiting_reason"))
            self.ui.taskContextStatusLabel.setText(self._t("memory_waiting"))
        self._update_memory_action_state()

    @Slot()
    def _project_rail_clicked(self) -> None:
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self.set_review_mode(self._project_review_mode)
        elif not self._task_pane_expanded:
            self._toggle_task_pane()

    @Slot()
    def _memory_rail_clicked(self) -> None:
        self.set_review_mode(ReviewMode.MEMORY_EDIT)

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
            return

        self.ui.taskPane.show()
        splitter.setSizes(list(self._expanded_splitter_sizes))
        self._task_pane_expanded = True
        self.ui.taskPaneCollapseButton.setToolTip(self._t("collapse_tasks"))

    def load_task_list(self) -> None:
        """Load lightweight task summaries without blocking the Qt thread."""

        self._task_generation += 1
        self._sensitive_scan_generation += 1
        self._close_sensitive_progress_dialog()
        self._sensitive_matches.clear()
        self._sensitive_scan_complete = False
        self.ui.sensitiveScanButton.blockSignals(True)
        self.ui.sensitiveScanButton.setChecked(False)
        self.ui.sensitiveScanButton.blockSignals(False)
        generation = self._task_generation
        self.ui.taskRefreshButton.setEnabled(False)
        self.ui.taskListStatusLabel.setText(self._t("task_list_loading"))

        def load() -> tuple[ThreadSnapshot, ...] | CleanupCandidateInventory:
            if self.review_mode is ReviewMode.CONVERSATION_CLEANUP and (
                self._cleanup_candidate_ids or self._cleanup_loaded_candidate_ids
            ):
                root_ids = tuple(
                    dict.fromkeys(
                        (*self._cleanup_candidate_ids, *self._cleanup_loaded_candidate_ids)
                    )
                )
                return self.workflows.inspect_cleanup_candidates(root_ids)
            return self.workflows.list_threads(
                include_active=True,
                include_archived=True,
            ).snapshots

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
        if isinstance(value, CleanupCandidateInventory):
            snapshots = value.snapshots
            self._verified_backup_ids = value.verified_backup_ids
            by_id = {snapshot.id: snapshot for snapshot in snapshots}
            safe_loaded_ids = tuple(
                thread_id
                for thread_id in self._cleanup_loaded_candidate_ids
                if self._can_archive_root(thread_id, by_id)
            )
            self._supplemental_candidate_ids = tuple(
                dict.fromkeys((*safe_loaded_ids, *value.supplemental_root_ids))
            )
            self._purge_candidate_ids = value.purge_root_ids
        elif isinstance(value, tuple) and all(
            isinstance(snapshot, ThreadSnapshot) for snapshot in value
        ):
            snapshots = value
            self._verified_backup_ids = frozenset()
            self._supplemental_candidate_ids = ()
            self._purge_candidate_ids = ()
        else:
            self._task_list_failed(generation, self._t("task_list_invalid"))
            return
        self._all_task_snapshots = snapshots
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
            return
        missing = 0
        if self.review_mode is ReviewMode.CONVERSATION_CLEANUP and self._cleanup_candidate_ids:
            by_id = {snapshot.id: snapshot for snapshot in snapshots}
            display_ids = tuple(
                dict.fromkeys(
                    (
                        *self._cleanup_candidate_ids,
                        *self._cleanup_loaded_candidate_ids,
                        *self._supplemental_candidate_ids,
                    )
                )
            )
            snapshots = tuple(by_id[thread_id] for thread_id in display_ids if thread_id in by_id)
            missing = sum(thread_id not in by_id for thread_id in self._cleanup_candidate_ids)
        self.task_snapshots = snapshots
        self._populate_task_list(snapshots)
        if self._cleanup_initial_selection_pending:
            self._select_task_ids(())
            self._cleanup_initial_selection_pending = False
        elif self._cleanup_loaded_selection_pending is not None:
            self._select_task_ids((self._cleanup_loaded_selection_pending,))
            self._cleanup_loaded_selection_pending = None
        if self.review_mode is ReviewMode.CONVERSATION_CLEANUP:
            self.ui.taskListStatusLabel.setText(
                self._t(
                    "cleanup_candidate_count",
                    count=len(self._cleanup_candidate_ids) - missing,
                    supplemental=len(self._supplemental_candidate_ids),
                    purge=len(self._purge_candidate_ids),
                    missing=missing,
                )
            )
        else:
            self.ui.taskListStatusLabel.setText(
                self._t("task_list_count_search", count=len(snapshots))
            )

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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
        else:
            self._populate_task_list(self.task_snapshots)

    @Slot()
    def _task_selection_changed(self) -> None:
        if self._task_selection_guard or self._closing:
            return
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            current = self.ui.taskListView.currentItem()
            if current is not None:
                self._show_memory_source(current)
        self._update_task_action_state()

    @Slot(QTreeWidgetItem, int)
    def _task_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._task_selection_guard or self._closing:
            return
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._show_memory_source(item)
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
                    if (
                        self.review_mode is ReviewMode.CONVERSATION_CLEANUP
                        and snapshot.id in self._supplemental_candidate_ids
                    ):
                        title = self._t("cleanup_supplemental_title", title=title)
                    item = QTreeWidgetItem([title, self._relative_age(snapshot)])
                    item.setData(0, Qt.ItemDataRole.UserRole, snapshot.id)
                    item.setToolTip(0, self._task_tooltip(snapshot))
                    item.setToolTip(1, self._activity_tooltip(snapshot))
                    suggestion = self._cleanup_suggestions.get(snapshot.id)
                    if (
                        self.review_mode is ReviewMode.CONVERSATION_CLEANUP
                        and suggestion is not None
                    ):
                        item.setIcon(
                            0,
                            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
                        )
                        item.setToolTip(
                            0,
                            self._task_tooltip(snapshot)
                            + "\n"
                            + self._t(
                                "cleanup_suggestion_tooltip",
                                confidence=round(suggestion.confidence * 100),
                                reason=suggestion.reason,
                            ),
                        )
                    elif (
                        self.review_mode is ReviewMode.CONVERSATION_CLEANUP
                        and snapshot.id in self._supplemental_candidate_ids
                    ):
                        item.setIcon(
                            0,
                            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder),
                        )
                        item.setToolTip(
                            0,
                            self._task_tooltip(snapshot)
                            + "\n"
                            + self._t("cleanup_supplemental_tooltip"),
                        )
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
                    if self.review_mode is ReviewMode.CONVERSATION_CLEANUP:
                        closure_ids = (snapshot.id, *snapshot.spawned_descendant_ids)
                        cleanup_by_id = {
                            candidate.id: candidate for candidate in self._all_task_snapshots
                        }
                        verified_count = sum(
                            thread_id in self._verified_backup_ids for thread_id in closure_ids
                        )
                        item.setToolTip(
                            0,
                            item.toolTip(0)
                            + "\n"
                            + self._t(
                                "cleanup_scope_tooltip",
                                size=self._format_size(
                                    sum(
                                        candidate.size_bytes
                                        for candidate in self._all_task_snapshots
                                        if candidate.id in closure_ids
                                    )
                                ),
                                descendants=len(snapshot.spawned_descendant_ids),
                                verified=verified_count,
                                total=len(closure_ids),
                                risk=(
                                    self._t("cleanup_risk_ready")
                                    if self._can_archive_root(snapshot.id, cleanup_by_id)
                                    else self._t("cleanup_risk_blocked")
                                ),
                            ),
                        )
                        self._append_cleanup_descendants(item, snapshot)
                self.ui.taskListView.addTopLevelItem(group)
                group.setExpanded(True)
            if self.review_mode is ReviewMode.CONVERSATION_CLEANUP:
                self._append_purge_candidates(query)
            for selected_id in selected_ids:
                self._select_task_in_list(selected_id, clear=False)
        finally:
            self._task_selection_guard = False
        self._update_task_action_state()

    def _append_purge_candidates(self, query: str) -> None:
        by_id = {snapshot.id: snapshot for snapshot in self._all_task_snapshots}
        candidates = [
            by_id[thread_id]
            for thread_id in self._purge_candidate_ids
            if thread_id in by_id and (not query or self._task_matches(by_id[thread_id], query))
        ]
        if not candidates:
            return
        group = QTreeWidgetItem([self._t("cleanup_purge_group"), ""])
        group.setFirstColumnSpanned(True)
        group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        group.setToolTip(0, self._t("cleanup_purge_group_tooltip"))
        for snapshot in sorted(candidates, key=self._task_sort_key):
            title = snapshot.title.strip() or self._t("unnamed_task")
            item = QTreeWidgetItem(
                [
                    self._t("cleanup_purge_candidate", title=title),
                    self._relative_age(snapshot),
                ]
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setIcon(
                0,
                self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),
            )
            scope_ids = (snapshot.id, *snapshot.spawned_descendant_ids)
            item.setToolTip(
                0,
                self._task_tooltip(snapshot)
                + "\n"
                + self._t(
                    "cleanup_purge_candidate_tooltip",
                    descendants=len(snapshot.spawned_descendant_ids),
                    size=self._format_size(
                        sum(
                            candidate.size_bytes
                            for candidate in self._all_task_snapshots
                            if candidate.id in scope_ids
                        )
                    ),
                ),
            )
            group.addChild(item)
        self.ui.taskListView.addTopLevelItem(group)
        group.setExpanded(True)

    def _append_cleanup_descendants(
        self,
        root_item: QTreeWidgetItem,
        root: ThreadSnapshot,
    ) -> None:
        by_id = {snapshot.id: snapshot for snapshot in self._all_task_snapshots}
        for thread_id in root.spawned_descendant_ids:
            snapshot = by_id.get(thread_id)
            if snapshot is None:
                child = QTreeWidgetItem(
                    [self._t("cleanup_missing_descendant", thread_id=thread_id), "—"]
                )
                child.setIcon(
                    0,
                    self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical),
                )
                child.setToolTip(0, self._t("cleanup_missing_descendant_tooltip"))
            else:
                title = snapshot.title.strip() or self._t("unnamed_task")
                child = QTreeWidgetItem(
                    [self._t("cleanup_descendant", title=title), self._relative_age(snapshot)]
                )
                child.setToolTip(
                    0,
                    self._task_tooltip(snapshot)
                    + "\n"
                    + self._t(
                        "cleanup_descendant_tooltip",
                        size=self._format_size(snapshot.size_bytes),
                        backup=(
                            self._t("cleanup_backup_verified")
                            if snapshot.id in self._verified_backup_ids
                            else self._t("cleanup_backup_missing")
                        ),
                    ),
                )
                child.setToolTip(1, self._activity_tooltip(snapshot))
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            root_item.addChild(child)
        root_item.setExpanded(True)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        value = float(size_bytes)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if value < 1024 or unit == "GiB":
                rendered = f"{value:.1f}".rstrip("0").rstrip(".")
                return f"{rendered} {unit}"
            value /= 1024
        return f"{size_bytes} B"

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

    def _select_task_ids(self, thread_ids: tuple[str, ...]) -> None:
        wanted = set(thread_ids)
        self._task_selection_guard = True
        try:
            self.ui.taskListView.clearSelection()
            first: QTreeWidgetItem | None = None
            for group_index in range(self.ui.taskListView.topLevelItemCount()):
                group = self.ui.taskListView.topLevelItem(group_index)
                if group is None:
                    continue
                for item_index in range(group.childCount()):
                    item = group.child(item_index)
                    if item.data(0, Qt.ItemDataRole.UserRole) not in wanted:
                        continue
                    item.setSelected(True)
                    if first is None:
                        first = item
            if first is not None:
                self.ui.taskListView.setCurrentItem(first)
        finally:
            self._task_selection_guard = False
            self._update_task_action_state()

    def _populate_memory_sources(self) -> None:
        query = self.ui.threadIdEdit.text().strip().casefold()
        try:
            sources = self.memory_service.sources.list()
        except (OSError, ValueError) as exc:
            self._show_error(self._t("memory_sources_failed", error=exc))
            return
        if self._memory_paths:
            requested = {
                Path(value).expanduser().resolve(strict=False) for value in self._memory_paths
            }
            sources = tuple(
                source for source in sources if source.path.resolve(strict=False) in requested
            )
        visible_sources = tuple(
            source
            for source in sources
            if not query
            or query in source.source_id.casefold()
            or query in source.relative_path.casefold()
            or query in str(source.path).casefold()
        )
        self._task_selection_guard = True
        try:
            self.ui.taskListView.clear()
            group = QTreeWidgetItem([self._t("memory_sources"), ""])
            group.setFirstColumnSpanned(True)
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for source in visible_sources:
                item = QTreeWidgetItem([source.relative_path, self._t("memory_registered")])
                item.setData(0, Qt.ItemDataRole.UserRole, source.source_id)
                item.setToolTip(
                    0,
                    self._t(
                        "memory_source_tooltip",
                        path=source.path,
                        source_id=source.source_id,
                    ),
                )
                group.addChild(item)
            self.ui.taskListView.addTopLevelItem(group)
            group.setExpanded(True)
            if group.childCount():
                first = group.child(0)
                self.ui.taskListView.setCurrentItem(first)
                first.setSelected(True)
                self._show_memory_source(first)
        finally:
            self._task_selection_guard = False
        self.ui.taskListStatusLabel.setText(
            self._t("memory_source_count", count=len(visible_sources))
        )
        self._update_task_action_state()

    def _show_memory_source(self, item: QTreeWidgetItem) -> None:
        source_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(source_id, str) or not source_id:
            return
        try:
            snapshot = self.memory_service.snapshot(source_id)
        except (KeyError, OSError, ValueError) as exc:
            self._show_error(self._t("memory_load_failed", error=exc))
            return
        self.memory_snapshot = snapshot
        self.memory_selections = {
            segment.segment_id: MemorySelection(
                segment_id=segment.segment_id,
                action=(MemoryAction.PROTECT if segment.protected else MemoryAction.KEEP),
                reason=segment.protection_reason or self._t("memory_default_keep_reason"),
            )
            for segment in snapshot.segments
        }
        applied_suggestions, ignored_suggestions = self._inject_memory_suggestions(snapshot)
        self.current_memory_plan = None
        self.memory_timeline_model = MemorySegmentModel(
            snapshot,
            self.memory_selections,
            self,
            language=self._language,
        )
        self.ui.timelineView.setModel(self.memory_timeline_model)
        self._configure_views()
        selection_model = self.ui.timelineView.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._memory_selection_changed)
        if snapshot.segments:
            preferred = next(
                (index for index, segment in enumerate(snapshot.segments) if not segment.protected),
                0,
            )
            self.ui.timelineView.setCurrentIndex(self.memory_timeline_model.index(preferred, 0))
        self.ui.contentBrowser.setReadOnly(True)
        self.ui.taskContextStatusLabel.setText(
            self._t(
                "memory_external_suggestions_loaded",
                path=snapshot.relative_path,
                applied=applied_suggestions,
                ignored=ignored_suggestions,
            )
            if applied_suggestions or ignored_suggestions
            else self._t(
                "memory_source_loaded",
                path=snapshot.relative_path,
                segments=len(snapshot.segments),
                size=snapshot.size_bytes,
            )
        )
        self.ui.timelineHelp.setText(
            self._t(
                "memory_segment_summary",
                editable=sum(not segment.protected for segment in snapshot.segments),
                protected=sum(segment.protected for segment in snapshot.segments),
            )
        )
        self._update_memory_action_state()

    def _inject_memory_suggestions(self, snapshot: MemorySnapshot) -> tuple[int, int]:
        request = self.review_request
        bundle = self.review_bundle
        if (
            request is None
            or request.operation is not ReviewOperation.MEMORY_EDIT
            or bundle is None
        ):
            return 0, 0
        by_id = {segment.segment_id: segment for segment in snapshot.segments}
        action_map = {
            SuggestedAction.KEEP: MemoryAction.KEEP,
            SuggestedAction.DELETE: MemoryAction.DELETE,
            SuggestedAction.REPLACE: MemoryAction.REPLACE,
            SuggestedAction.PROTECT: MemoryAction.PROTECT,
        }
        applied = 0
        ignored = 0
        for suggestion in bundle.targets:
            if suggestion.target_id is None:
                ignored += 1
                continue
            segment = by_id.get(suggestion.target_id)
            action = action_map.get(suggestion.suggested_action)
            if (
                segment is None
                or action is None
                or suggestion.source_fingerprint != segment.content_sha256
            ):
                ignored += 1
                continue
            if segment.protected and action in {MemoryAction.DELETE, MemoryAction.REPLACE}:
                ignored += 1
                continue
            self.memory_selections[segment.segment_id] = MemorySelection(
                segment_id=segment.segment_id,
                action=action,
                replacement=(suggestion.suggested_text if action is MemoryAction.REPLACE else None),
                reason=suggestion.reason,
                suggested=True,
            )
            applied += 1
        return applied, ignored

    @Slot(QItemSelection, QItemSelection)
    def _memory_selection_changed(
        self,
        selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        if self.memory_timeline_model is None or not selected.indexes():
            return
        segment = self.memory_timeline_model.segment_for(selected.indexes()[0])
        if segment is not None:
            self._show_memory_segment(segment)

    def _show_memory_segment(self, segment: MemorySegment) -> None:
        self.current_memory_segment = segment
        self._updating_controls = True
        try:
            selection = self.memory_selections.get(segment.segment_id)
            action = selection.action if selection is not None else MemoryAction.KEEP
            self.ui.contentBrowser.setReadOnly(True)
            self.ui.contentBrowser.setPlainText(segment.text)
            self.ui.actionCombo.setCurrentIndex(INDEX_BY_MEMORY_ACTION[action])
            self.ui.summaryEdit.setPlainText(selection.replacement or "" if selection else "")
            self.ui.summaryEdit.setEnabled(action is MemoryAction.REPLACE and not segment.protected)
            self.ui.reasonBrowser.setPlainText(
                segment.protection_reason
                or (
                    selection.reason
                    if selection is not None
                    else self._t("memory_default_keep_reason")
                )
            )
            self.ui.riskLabel.setText(
                self._t("memory_protected_segment")
                if segment.protected
                else self._t("memory_editable_segment")
            )
        finally:
            self._updating_controls = False
        self._update_memory_action_state()

    def _memory_has_changes(self) -> bool:
        return any(
            selection.action in {MemoryAction.DELETE, MemoryAction.REPLACE}
            for selection in self.memory_selections.values()
        )

    def _update_memory_action_state(self) -> None:
        if self.review_mode is not ReviewMode.MEMORY_EDIT:
            return
        loaded = self.memory_snapshot is not None
        has_changes = loaded and self._memory_has_changes()
        self.ui.actionCombo.setEnabled(loaded and self.current_memory_segment is not None)
        self.ui.savePlanButton.setEnabled(bool(has_changes) and not self._write_in_progress)
        self.ui.applyButton.setEnabled(bool(has_changes) and not self._write_in_progress)

    def _selected_task_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for item in self.ui.taskListView.selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, str) and value:
                values.append(value)
        return tuple(dict.fromkeys(values))

    def _can_archive_selected_tasks(self) -> bool:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            return False
        by_id = {
            snapshot.id: snapshot for snapshot in (self._all_task_snapshots or self.task_snapshots)
        }
        return all(self._can_archive_root(thread_id, by_id) for thread_id in selected_ids)

    @staticmethod
    def _can_archive_root(
        thread_id: str,
        by_id: dict[str, ThreadSnapshot],
    ) -> bool:
        root = by_id.get(thread_id)
        if root is None:
            return False
        closure_ids = (root.id, *root.spawned_descendant_ids)
        for closure_id in closure_ids:
            snapshot = by_id.get(closure_id)
            if (
                snapshot is None
                or snapshot.archived
                or snapshot.pinned
                or snapshot.ephemeral
                or snapshot.status not in SAFE_INACTIVE_STATUSES
                or not snapshot.mapping_complete
                or not snapshot.content_complete
            ):
                return False
        return True

    def _update_task_action_state(self) -> None:
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self.ui.taskBackupButton.setEnabled(False)
            self.ui.taskArchiveButton.setEnabled(False)
            self.ui.taskDeleteButton.setEnabled(False)
            return
        enabled = bool(self._selected_task_ids()) and not self._task_write_in_progress
        if self.review_mode is ReviewMode.CONVERSATION_CLEANUP:
            self.ui.taskBackupButton.setEnabled(enabled and self._can_archive_selected_tasks())
            self.ui.taskArchiveButton.setEnabled(False)
            self.ui.taskDeleteButton.setEnabled(False)
            return
        self.ui.taskBackupButton.setEnabled(enabled)
        self.ui.taskArchiveButton.setEnabled(enabled and self._can_archive_selected_tasks())
        self.ui.taskDeleteButton.setEnabled(enabled)

    @Slot(QPoint)
    def _show_task_context_menu(self, point: QPoint) -> None:
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            return
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
        backup_action = menu.addAction(
            self._t(
                "cleanup_backup_archive_selected"
                if self.review_mode is ReviewMode.CONVERSATION_CLEANUP
                else "backup_selected",
                count=selected_count,
            )
        )
        archive_action = menu.addAction(self._t("archive_selected", count=selected_count))
        delete_action = menu.addAction(self._t("delete_selected", count=selected_count))
        rename_action.setVisible(self.review_mode is ReviewMode.CONTEXT_TRIM)
        archive_action.setVisible(self.review_mode is ReviewMode.CONTEXT_TRIM)
        delete_action.setVisible(self.review_mode is ReviewMode.CONTEXT_TRIM)
        rename_action.setEnabled(not self._task_write_in_progress)
        backup_action.setEnabled(
            not self._task_write_in_progress
            and (
                self.review_mode is not ReviewMode.CONVERSATION_CLEANUP
                or self._can_archive_selected_tasks()
            )
        )
        archive_action.setEnabled(
            not self._task_write_in_progress and self._can_archive_selected_tasks()
        )
        delete_action.setEnabled(not self._task_write_in_progress)
        rename_action.triggered.connect(lambda _checked=False: self._rename_task(thread_id))
        copy_action.triggered.connect(lambda _checked=False: self._copy_conversation_id(thread_id))
        backup_action.triggered.connect(self._task_backup_clicked)
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

    def _apply_task_rename(self, thread_id: str, new_name: str) -> ActionExecutionResult:
        return self.workflows.rename_thread(thread_id, new_name)

    def _task_rename_succeeded(self, value: object) -> None:
        if not isinstance(value, ActionExecutionResult):
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
    def _task_backup_clicked(self) -> None:
        if self.review_mode is ReviewMode.CONVERSATION_CLEANUP:
            self._backup_and_archive_selected_tasks()
        else:
            self._backup_selected_tasks()

    @Slot()
    def _backup_selected_tasks(self) -> None:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            self._show_error(self._t("select_task"))
            return
        settings = self._request_backup_settings(selected_ids, combined_archive=False)
        if settings is None:
            return
        destination = settings
        self._start_task_operation(
            self._t("backup_busy"),
            lambda: self._create_selected_backup(
                selected_ids,
                destination,
            ),
            self._task_backup_succeeded,
        )

    @Slot()
    def _backup_and_archive_selected_tasks(self) -> None:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            self._show_error(self._t("select_task"))
            return
        if not self._can_archive_selected_tasks():
            self._show_error(self._t("cleanup_selection_unsafe"))
            return
        settings = self._request_backup_settings(selected_ids, combined_archive=True)
        if settings is None:
            return
        destination = settings
        self._start_task_operation(
            self._t("cleanup_backup_archive_busy"),
            lambda: self._create_backup_and_archive(
                selected_ids,
                destination,
            ),
            self._task_backup_archive_succeeded,
        )

    def _request_backup_settings(
        self,
        selected_ids: tuple[str, ...],
        *,
        combined_archive: bool,
    ) -> Path | None:
        prefix = "cleanup-archive" if combined_archive else "codex-tasks"
        default_name = f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.csmbackup"
        selected_path, _filter = QFileDialog.getSaveFileName(
            self,
            self._t("backup_destination_title"),
            str(self.paths.backups_dir / default_name),
            "CodexSessionManager backup (*.csmbackup)",
        )
        if not selected_path:
            return None
        destination = Path(selected_path)
        if destination.suffix != ".csmbackup":
            destination = destination.with_name(destination.name + ".csmbackup")
        if destination.exists():
            self._show_error(self._t("task_operation_failed", error=FileExistsError(destination)))
            return None
        if not self.paths.managed_backup_identity_file.exists():
            create_key = QMessageBox.question(
                self,
                self._t("backup_managed_key_title"),
                self._t("backup_managed_key_create"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if create_key != QMessageBox.StandardButton.Yes:
                return None
        by_id = {snapshot.id: snapshot for snapshot in self._all_task_snapshots}
        affected_ids: list[str] = []
        for thread_id in selected_ids:
            root = by_id.get(thread_id)
            affected_ids.extend(
                (thread_id, *(root.spawned_descendant_ids if root is not None else ()))
            )
        affected_ids = list(dict.fromkeys(affected_ids))
        answer = QMessageBox.question(
            self,
            self._t(
                "cleanup_backup_archive_confirm_title"
                if combined_archive
                else "backup_confirm_title"
            ),
            self._t(
                "cleanup_backup_archive_confirm" if combined_archive else "backup_confirm",
                selected=len(selected_ids),
                filename=destination.name,
                root_ids="\n".join(f"• {thread_id}" for thread_id in selected_ids),
                affected=len(affected_ids),
                affected_ids="\n".join(f"• {thread_id}" for thread_id in affected_ids),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        return destination

    def _create_selected_backup(
        self,
        selected_ids: tuple[str, ...],
        destination: Path,
    ) -> BackupCreationResult:
        return self.workflows.create_managed_backup(
            destination,
            thread_ids=selected_ids,
            include_raw=True,
            expand_descendants=True,
        )

    def _create_backup_and_archive(
        self,
        selected_ids: tuple[str, ...],
        destination: Path,
    ) -> BackupArchiveResult:
        return self.workflows.backup_and_archive_managed(
            destination,
            selected_ids=selected_ids,
            review_request=self.review_request,
            include_raw=True,
        )

    def _task_backup_succeeded(self, value: object) -> None:
        if not isinstance(value, BackupCreationResult):
            self._show_error(self._t("backup_invalid"))
            return
        QMessageBox.information(
            self,
            self._t("backup_done_title"),
            self._t(
                "backup_done",
                count=len(value.covered_thread_ids),
                manifest_sha256=value.manifest.manifest_sha256,
            ),
        )
        self.ui.taskListStatusLabel.setText(
            self._t(
                "backup_done",
                count=len(value.covered_thread_ids),
                manifest_sha256=value.manifest.manifest_sha256,
            ).split("\n", maxsplit=1)[0]
        )

    def _task_backup_archive_succeeded(self, value: object) -> None:
        if not isinstance(value, BackupArchiveResult):
            self._show_error(self._t("cleanup_backup_archive_invalid"))
            return
        QMessageBox.information(
            self,
            self._t("cleanup_backup_archive_done_title"),
            self._t(
                "cleanup_backup_archive_done",
                covered=len(value.backup.covered_thread_ids),
                roots=len(value.action.completed_ids),
                manifest_sha256=value.backup.manifest.manifest_sha256,
                plan_id=value.action.plan.plan_id,
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
        if (
            self.review_mode is ReviewMode.CONVERSATION_CLEANUP
            and self.review_request is not None
            and self.review_request.suggestion_bundle_path
        ):
            return prepare_cleanup_action_plan(
                self.paths,
                self.review_request,
                selected_ids,
                allow_user_additions=True,
            )
        return self.workflows.prepare_selected_archive(selected_ids).plan

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

    def _apply_prepared_archive(self, plan: ActionPlan) -> ActionExecutionResult:
        return self.workflows.apply_action(plan, confirmation=plan.plan_id)

    def _task_archive_succeeded(self, value: object) -> None:
        if not isinstance(value, ActionExecutionResult):
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
        return self.workflows.prepare_selected_purge(selected_ids).plan

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
    ) -> ActionExecutionResult:
        return self.workflows.apply_action(
            plan,
            confirmation=confirmation,
            permanent_phrase=permanent_phrase,
        )

    def _task_purge_succeeded(self, value: object) -> None:
        if not isinstance(value, ActionExecutionResult):
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
        if not checked:
            self._close_sensitive_progress_dialog()
            if self.current_target is not None:
                self._apply_content_overlays()
            self._populate_task_list(self.task_snapshots)
            self.ui.taskListStatusLabel.setText(
                self._t("sensitive_off", count=len(self.task_snapshots))
            )
            return
        if self.current_target is not None:
            self._apply_content_overlays()
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
        self._show_sensitive_progress_dialog(total)

        worker: FunctionWorker

        def scan() -> SensitiveScanBatch:
            return self.workflows.scan_sensitive_threads(
                tuple(snapshot.id for snapshot in self.task_snapshots),
                cancelled=lambda: generation != self._sensitive_scan_generation or self._closing,
                progress=worker.signals.progress.emit,
            )

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

    def _show_sensitive_progress_dialog(self, total: int) -> None:
        self._close_sensitive_progress_dialog()
        dialog = QProgressDialog(
            self._t("sensitive_progress", current=0, total=total),
            self._t("sensitive_progress_cancel"),
            0,
            total,
            self,
        )
        dialog.setWindowTitle(self._t("sensitive_progress_title"))
        dialog.setAccessibleName(self._t("sensitive_progress_title"))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setMinimumWidth(520)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.canceled.connect(self._cancel_sensitive_scan)
        self._sensitive_progress_dialog = dialog
        dialog.show()

    def _close_sensitive_progress_dialog(self) -> None:
        dialog = self._sensitive_progress_dialog
        self._sensitive_progress_dialog = None
        if dialog is None:
            return
        dialog.reset()
        dialog.close()
        dialog.deleteLater()

    @Slot()
    def _cancel_sensitive_scan(self) -> None:
        if self.ui.sensitiveScanButton.isChecked():
            self.ui.sensitiveScanButton.setChecked(False)
        else:
            self._close_sensitive_progress_dialog()

    def _sensitive_scan_progress(self, generation: int, value: object) -> None:
        if generation != self._sensitive_scan_generation or not isinstance(value, tuple):
            return
        if len(value) != 2 or not all(isinstance(item, int) for item in value):
            return
        current, total = value
        message = self._t("sensitive_progress", current=current, total=total)
        self.ui.taskListStatusLabel.setText(message)
        if self._sensitive_progress_dialog is not None:
            self._sensitive_progress_dialog.setMaximum(total)
            self._sensitive_progress_dialog.setLabelText(message)
            self._sensitive_progress_dialog.setValue(current)

    def _sensitive_scan_loaded(self, generation: int, value: object) -> None:
        if (
            generation != self._sensitive_scan_generation
            or self._closing
            or not self.ui.sensitiveScanButton.isChecked()
        ):
            return
        if not isinstance(value, SensitiveScanBatch):
            self._sensitive_scan_failed(generation, self._t("sensitive_invalid_result"))
            return
        self._close_sensitive_progress_dialog()
        if value.cancelled:
            self.ui.sensitiveScanButton.setChecked(False)
            return
        self._sensitive_matches = value.matches
        self._sensitive_scan_complete = True
        self._populate_task_list(self.task_snapshots)
        self._show_sensitive_summary(value.failed)

    def _sensitive_scan_failed(self, generation: int, error: str) -> None:
        if generation != self._sensitive_scan_generation or self._closing:
            return
        self._close_sensitive_progress_dialog()
        self.ui.sensitiveScanButton.setChecked(False)
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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
            return
        query = self.ui.threadIdEdit.text().strip()
        if not query:
            return
        if any(snapshot.id == query for snapshot in self.task_snapshots):
            self.load_thread(query)
            return
        self.ui.taskListStatusLabel.setText(self._t("query_filtered"))

    @Slot()
    def _load_from_edit(self) -> None:
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._populate_memory_sources()
            return
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
            result = self.workflows.read_thread(thread_id, include_turns=True)
            suggested = LocalTrimSuggester().suggest(
                result.snapshot,
                capabilities=result.capabilities,
                trigger=self.trigger,
                source_turn_id=self.source_turn_id,
            )
            applied: tuple[str, ...] = ()
            ignored: tuple[str, ...] = ()
            request = self.review_request
            bundle = self.review_bundle
            if (
                self.review_mode is ReviewMode.CONTEXT_TRIM
                and request is not None
                and request.operation is ReviewOperation.CONTEXT_TRIM
                and request.target_ids == (thread_id,)
                and bundle is not None
            ):
                external = ExternalSuggestionBundleProvider().apply(
                    snapshot=result.snapshot,
                    base_plan=suggested,
                    bundle=bundle,
                )
                suggested = external.plan
                applied = external.applied_target_ids
                ignored = external.ignored_protected_target_ids
            pending_override = self._pending_plan_override
            if pending_override is not None:
                pending_override.verify()
                if pending_override.source_thread_id != result.snapshot.id:
                    raise ValueError("pending TrimPlan belongs to another conversation")
                if pending_override.source_thread_fingerprint != result.snapshot.trim_fingerprint:
                    raise ValueError("pending TrimPlan source fingerprint changed")
                if pending_override.capability_fingerprint != result.capabilities.fingerprint:
                    raise ValueError("pending TrimPlan capability fingerprint changed")
                validate_selections(result.snapshot, pending_override.selections)
                suggested = pending_override
            return ReviewDocument(
                result.snapshot,
                result.capabilities,
                suggested,
                applied,
                ignored,
            )

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
        self.review_state = ReviewState.from_selections(
            value.snapshot,
            value.suggested_plan.selections,
        )
        self.selections = self.review_state.selections
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
        if self.review_mode is ReviewMode.CONVERSATION_CLEANUP and value.snapshot.id not in {
            snapshot.id for snapshot in self.task_snapshots
        }:
            self._cleanup_loaded_candidate_ids = tuple(
                dict.fromkeys((*self._cleanup_loaded_candidate_ids, value.snapshot.id))
            )
            self._cleanup_loaded_selection_pending = value.snapshot.id
            self.load_task_list()
        else:
            self._select_task_in_list(
                value.snapshot.id,
                clear=self.review_mode is not ReviewMode.CONVERSATION_CLEANUP,
            )
        self.ui.savePlanButton.setEnabled(not self.hook_mode or value.capabilities.write_enabled)
        self.ui.applyButton.setEnabled(
            not self.hook_mode and value.snapshot.status in SAFE_INACTIVE_STATUSES
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
        if value.external_applied_target_ids or value.external_ignored_target_ids:
            self.ui.taskContextStatusLabel.setText(
                self._t(
                    "external_suggestions_loaded",
                    applied=len(value.external_applied_target_ids),
                    ignored=len(value.external_ignored_target_ids),
                )
            )
        self._apply_review_mode()

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
            if self.review_mode is ReviewMode.CONVERSATION_CLEANUP and self.document is not None:
                suggestion = self._cleanup_suggestions.get(self.document.snapshot.id)
                if suggestion is not None:
                    self.ui.reasonBrowser.setPlainText(suggestion.reason)
                    self.ui.riskLabel.setText(
                        self._t(
                            "cleanup_confidence",
                            confidence=round(suggestion.confidence * 100),
                        )
                    )
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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            return
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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._memory_action_changed(index)
            return
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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._memory_replacement_changed()
            return
        if self._updating_controls or self.current_target is None:
            return
        selection = self.selections.get(self.current_target.id)
        if selection is None or selection.action is not TrimAction.SUMMARY:
            return
        text = self.ui.summaryEdit.toPlainText().strip()
        if text:
            self.selections[self.current_target.id] = selection.model_copy(update={"summary": text})
            self._update_estimate()

    def _memory_action_changed(self, index: int) -> None:
        if self._updating_controls or self.current_memory_segment is None:
            return
        segment = self.current_memory_segment
        action = MEMORY_ACTION_BY_INDEX[index]
        if segment.protected and action in {MemoryAction.DELETE, MemoryAction.REPLACE}:
            self._show_error(self._t("memory_hard_protected_action"))
            self._show_memory_segment(segment)
            return
        existing = self.memory_selections.get(segment.segment_id)
        replacement = self.ui.summaryEdit.toPlainText()
        if action is MemoryAction.REPLACE and not replacement:
            replacement = segment.text.rstrip("\r\n")
        self.memory_selections[segment.segment_id] = MemorySelection(
            segment_id=segment.segment_id,
            action=action,
            replacement=replacement if action is MemoryAction.REPLACE else None,
            reason=(
                segment.protection_reason
                if action is MemoryAction.PROTECT and segment.protection_reason
                else existing.reason
                if existing is not None
                else self._t("memory_manual_reason")
            ),
            suggested=False,
        )
        self._updating_controls = True
        try:
            self.ui.summaryEdit.setEnabled(action is MemoryAction.REPLACE)
            if action is MemoryAction.REPLACE:
                self.ui.summaryEdit.setPlainText(replacement)
            else:
                self.ui.summaryEdit.clear()
        finally:
            self._updating_controls = False
        if self.memory_timeline_model is not None:
            self.memory_timeline_model.selections = self.memory_selections
            self.memory_timeline_model.refresh_actions()
        self._update_memory_action_state()

    def _memory_replacement_changed(self) -> None:
        if self._updating_controls or self.current_memory_segment is None:
            return
        segment = self.current_memory_segment
        selection = self.memory_selections.get(segment.segment_id)
        if selection is None or selection.action is not MemoryAction.REPLACE:
            return
        self.memory_selections[segment.segment_id] = selection.model_copy(
            update={"replacement": self.ui.summaryEdit.toPlainText()}
        )
        self._update_memory_action_state()

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
        self.review_state = ReviewState.from_selections(
            self.document.snapshot,
            plan.selections,
        )
        self.selections = self.review_state.selections
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
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._save_memory_plan()
            return
        try:
            plan = self._build_plan()
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(self._t("plan_save_failed", error=exc))
            return
        if self._write_in_progress:
            self._show_error(self._t("write_in_progress"))
            return
        self._set_busy(True, self._t("plan_save_busy"))
        self._write_in_progress = True
        generation = self._generation
        outcome: dict[str, object] = {}

        def save() -> TrimPlan:
            self.workflows.save_plan(plan)
            return plan

        worker = FunctionWorker(save, self._worker_owner)
        worker.signals.result.connect(lambda value: outcome.__setitem__("value", value))
        worker.signals.error.connect(lambda error: outcome.__setitem__("error", error))
        worker.signals.finished.connect(
            lambda current=generation: self._save_plan_finished(current, outcome)
        )
        self.thread_pool.start(worker)

    def _save_plan_finished(self, generation: int, outcome: dict[str, object]) -> None:
        self._write_in_progress = False
        if generation != self._generation or self._closing:
            return
        self._set_busy(False)
        error = outcome.get("error")
        if isinstance(error, str):
            self._show_error(self._t("plan_save_failed", error=error))
            return
        value = outcome.get("value")
        if not isinstance(value, TrimPlan):
            self._show_error(self._t("plan_save_no_result"))
            return
        self.current_plan = value
        self.ui.errorLabel.setText(self._t("plan_saved", plan_id=value.plan_id))
        self.ui.errorLabel.show()
        self.plan_saved.emit(value)
        if self.hook_mode:
            self.close()

    @Slot()
    def _apply_plan(self) -> None:
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._apply_memory_plan()
            return
        try:
            plan = self._build_plan()
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(self._t("plan_validate_failed", error=exc))
            return
        if self._write_in_progress:
            self._show_error(self._t("write_in_progress"))
            return
        self._set_busy(True, self._t("apply_busy"))
        self._write_in_progress = True
        generation = self._generation

        def apply() -> str:
            self.workflows.save_plan(plan)
            return self.workflows.apply_trim(plan)

        worker = FunctionWorker(apply, self._worker_owner)
        worker.signals.result.connect(
            lambda value, current=generation: self._apply_succeeded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._apply_failed(current, message)
        )
        worker.signals.finished.connect(lambda current=generation: self._apply_finished(current))
        self.thread_pool.start(worker)

    def _build_memory_plan(self) -> tuple[MemoryPlan, str]:
        snapshot = self.memory_snapshot
        if snapshot is None:
            raise ValueError("no memory source is loaded")
        plan = MemoryPlan.create(snapshot, tuple(self.memory_selections.values()))
        result = render_memory(snapshot, plan.selections)
        diff = memory_unified_diff(snapshot, result)
        if not diff:
            raise ValueError("memory selections do not change the source")
        return plan, diff

    def _save_memory_plan(self) -> None:
        if self._write_in_progress:
            self._show_error(self._t("write_in_progress"))
            return
        try:
            plan, diff = self._build_memory_plan()
            path = self.memory_service.plans.save(plan)
        except (OSError, ValueError) as exc:
            self._show_error(self._t("memory_plan_failed", error=exc))
            return
        self.current_memory_plan = plan
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(self._t("memory_plan_saved_title"))
        dialog.setText(
            self._t(
                "memory_plan_saved",
                plan_id=plan.plan_id,
                path=path,
            )
        )
        dialog.setDetailedText(diff)
        dialog.exec()
        self.plan_saved.emit(plan)

    def _apply_memory_plan(self) -> None:
        if self._write_in_progress:
            self._show_error(self._t("write_in_progress"))
            return
        try:
            plan, diff = self._build_memory_plan()
            self.memory_service.plans.save(plan)
        except (OSError, ValueError) as exc:
            self._show_error(self._t("memory_plan_failed", error=exc))
            return
        confirmation = QMessageBox(self)
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setWindowTitle(self._t("memory_apply_confirm_title"))
        confirmation.setText(
            self._t(
                "memory_apply_confirm",
                plan_id=plan.plan_id,
                path=plan.source_path,
            )
        )
        confirmation.setDetailedText(diff)
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        if confirmation.exec() != QMessageBox.StandardButton.Yes:
            return
        self._write_in_progress = True
        self._set_busy(True, self._t("memory_apply_busy"))
        try:
            result = self.memory_service.apply(plan, confirmation=plan.plan_id)
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_error(self._t("memory_apply_failed", error=exc))
            return
        finally:
            self._write_in_progress = False
            self._set_busy(False)
        self.current_memory_plan = plan
        self._memory_apply_succeeded(result)

    def _memory_apply_succeeded(self, result: MemoryApplyResult) -> None:
        QMessageBox.information(
            self,
            self._t("memory_apply_done_title"),
            self._t(
                "memory_apply_done",
                backup_id=result.backup_id,
                content_sha256=result.content_sha256,
            ),
        )
        current = self.ui.taskListView.currentItem()
        if current is not None:
            self._show_memory_source(current)

    def _apply_succeeded(self, generation: int, value: object) -> None:
        if generation != self._generation or self._closing:
            return
        thread_id = str(value)
        pending = self.pending_trim_plan
        if pending is not None:
            try:
                store = PendingTrimPlanStore(self.paths)
                current = store.load(store.path_for(pending.plan_id))
                self.pending_trim_plan = PendingPlanService(store).applied(current)
            except (OSError, ValueError) as exc:
                self._show_error(self._t("pending_state_update_failed", error=exc))
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
        if self.document is None or self.review_state is None:
            return 0
        return self.review_state.estimated_tokens_after()

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
                before=compact_number(before),
                after=compact_number(after),
                saved=compact_number(saved),
            )
        )
        self.ui.savingProgress.setValue(percent)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.ui.loadButton.setEnabled(not busy)
        if self.review_mode is ReviewMode.MEMORY_EDIT:
            self._update_memory_action_state()
            if busy:
                self.ui.savePlanButton.setEnabled(False)
                self.ui.applyButton.setEnabled(False)
            if message:
                self.ui.taskContextStatusLabel.setText(message)
                self.ui.taskContextStatusLabel.setToolTip(message)
            return
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

        if self.review_state is None:
            return
        self.review_state.normalize_selection_scope(
            target,
            keep_reason=self._t("manual_reason"),
        )

    @staticmethod
    def _target_protected_reasons(
        target: TurnSnapshot | ThreadItemSnapshot,
    ) -> tuple[str, ...]:
        return protected_reasons(target)

    @staticmethod
    def _target_text(target: TurnSnapshot | ThreadItemSnapshot) -> str:
        return target_text(target)

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
        self._close_sensitive_progress_dialog()
        self.window_closed.emit()
        super().closeEvent(event)
