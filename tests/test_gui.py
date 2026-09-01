from __future__ import annotations

import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
)

from codex_session_manager.gui import controller as controller_module
from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.gui.i18n import GuiLanguage, compact_number, missing_translation_keys
from codex_session_manager.gui.prompt import PrecompactPromptDialog
from codex_session_manager.gui.theme import (
    ACCENT,
    APP_STYLESHEET,
    DANGER,
    OUTLINE_STRONG,
    SPLITTER_LINE,
    TEXT,
)
from codex_session_manager.gui.widgets import CenteredHandleSplitter
from codex_session_manager.hashing import utc_now
from codex_session_manager.models import (
    BackupManifest,
    ContractIssue,
    ItemKind,
    OperationName,
    ThreadHistoryMode,
    ThreadItemSnapshot,
    ThreadStatus,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.sensitive import (
    SensitiveFinding,
    SensitiveScanResult,
    SensitiveSeverity,
    scan_sensitive_snapshot,
)
from codex_session_manager.workflows import (
    BackupCreationResult,
    InventoryResult,
    SensitiveScanBatch,
    ThreadReadResult,
)


def _document(snapshot, capabilities) -> ReviewDocument:
    selection = TrimSelection(
        target_id=snapshot.turns[0].id,
        action=TrimAction.KEEP,
        suggested=True,
    )
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(selection,),
        estimated_tokens_after=snapshot.token_estimate,
    )
    return ReviewDocument(snapshot, capabilities, plan)


def _block_operation(capabilities, operation: OperationName, subject: str):
    blocked = tuple(
        capability.model_copy(
            update={
                "available": False,
                "runtime_contract_fingerprint": None,
                "issues": (ContractIssue(code="test_blocked", subject=subject),),
            }
        )
        if capability.operation is operation
        else capability
        for capability in capabilities.operation_capabilities
    )
    return capabilities.model_copy(update={"operation_capabilities": blocked})


def test_review_window_layout_and_stale_worker_result(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    assert window.minimumWidth() == 1280
    assert window.minimumHeight() == 720
    assert window.width() == 1600
    assert window.height() == 900
    assert window.ui.heroFrame.maximumHeight() == 100
    assert window.ui.footerFrame.maximumHeight() == 54
    assert window.ui.appTitleLabel.text() == "CodexSessionManager"
    assert window.ui.headerBadge.text() == "原任务只读保护"
    assert window.ui.errorLabel.isHidden()
    assert window.ui.errorLabel.minimumHeight() == 0
    assert window.ui.errorLabel.maximumHeight() == 34
    assert window.ui.footerLayout.count() == 1
    assert window.ui.footerMainLayout.indexOf(window.ui.errorLabel) >= 0
    assert window.ui.reasonBrowser.minimumHeight() == 96
    assert window.ui.reasonBrowser.maximumHeight() == 140
    assert window.ui.taskListView.columnCount() == 2
    assert window.ui.taskListView.headerItem().text(1) == "距今"
    assert window._task_select_all_checkbox.accessibleName() == "全选当前筛选的任务"
    assert window.ui.threadIdEdit.parent() is window.ui.taskPane
    assert window.ui.manualTaskLayout.indexOf(window.ui.threadIdEdit) == 0
    assert window.ui.manualTaskLayout.indexOf(window.ui.loadButton) == 1
    assert window.ui.manualTaskLayout.indexOf(window.ui.taskFilterButton) == 2
    assert window.ui.taskListStatusLabel.text() == "尚未加载任务列表"
    assert not hasattr(window.ui, "olderThanDaysSpinBox")
    assert not hasattr(window.ui, "taskContextStatusLabel")
    assert not hasattr(window.ui, "taskDeleteButton")
    assert not hasattr(window.ui, "taskHelp")
    assert window.ui.taskPaneCollapseButton.text() == "收起"
    assert window.ui.taskBackupButton.text() == "备份"
    assert not window.ui.taskBackupButton.isEnabled()
    assert [
        window.ui.taskActionLayout.itemAt(index).widget().objectName()
        for index in range(window.ui.taskActionLayout.count())
    ] == ["taskRefreshButton", "taskBackupButton", "taskArchiveButton"]
    assert [
        window.ui.taskActionLayout.stretch(index)
        for index in range(window.ui.taskActionLayout.count())
    ] == [1, 1, 1]
    assert window.ui.taskPaneCollapseButton.icon().isNull()
    assert window.ui.toolRail.minimumWidth() == 44
    assert window.ui.toolRail.maximumWidth() == 44
    assert window.ui.toolRailLayout.count() == 3
    assert window.ui.projectTaskRailButton.isChecked()
    assert not window.ui.memoryRailButton.isChecked()
    assert not window.ui.sensitiveScanButton.isChecked()
    assert [
        window.ui.buttonLayout.itemAt(index).widget().objectName()
        for index in range(window.ui.buttonLayout.count())
    ] == ["sensitiveScanButton", "savePlanButton", "applyButton", "cancelButton"]
    assert window.ui.mainSplitter.handleWidth() == 8
    assert isinstance(window.ui.mainSplitter, CenteredHandleSplitter)
    assert window.ui.contentTagsButton.text() == "显示标签"
    assert window.ui.contentMarkdownButton.text() == "Markdown 预览"
    assert window.ui.contentTitle.text() == "上下文"
    assert window.ui.tokenLabel.minimumWidth() == 250
    assert (
        window.ui.taskListView.selectionMode() is QAbstractItemView.SelectionMode.ExtendedSelection
    )
    assert not hasattr(window.ui, "taskSearchEdit")
    assert window.ui.taskLayout.contentsMargins().right() == 4
    assert window.ui.timelineLayout.contentsMargins().left() == 4
    assert window.ui.timelineLayout.contentsMargins().right() == 4
    assert window.ui.contentLayout.contentsMargins().left() == 4
    assert window.ui.contentLayout.contentsMargins().right() == 4
    assert window.ui.actionLayout.contentsMargins().left() == 4
    assert (
        "QPen(QColor(SPLITTER_LINE), 1)"
        in (Path(__file__).parents[1] / "src/codex_session_manager/gui/widgets.py").read_text()
    )
    assert SPLITTER_LINE in APP_STYLESHEET
    assert "QLabel#reasonLabel, QLabel#summaryLabel" in APP_STYLESHEET
    assert "QComboBox::down-arrow" in APP_STYLESHEET
    assert "QComboBox QAbstractItemView" in APP_STYLESHEET
    assert "QTextEdit#contentBrowser" in APP_STYLESHEET
    assert "QLabel#tokenLabel" in APP_STYLESHEET
    assert "QPushButton#sensitiveScanButton" in APP_STYLESHEET
    assert "QSpinBox" in APP_STYLESHEET
    assert "background: #fff1f0" in APP_STYLESHEET

    stale = _document(snapshot_factory("stale"), capabilities)
    window._document_loaded(99, stale)
    assert window.document is None

    current = _document(snapshot_factory("current"), capabilities)
    window.task_snapshots = (current.snapshot,)
    window._populate_task_list(window.task_snapshots)
    window._document_loaded(0, current)
    assert window.document == current
    assert window.ui.timelineView.model().rowCount() == 1
    assert window.ui.timelineView.header().sectionResizeMode(0) is QHeaderView.ResizeMode.Stretch
    assert window.ui.savePlanButton.isEnabled()
    assert window.ui.tokenLabel.text().startswith("预计上下文")
    current_item = window.ui.taskListView.currentItem()
    assert current_item is not None
    assert current_item.data(0, Qt.ItemDataRole.UserRole) == "current"


def test_task_filter_defaults_to_active_and_switches_visible_inventory(
    qtbot, app_paths, snapshot_factory, monkeypatch
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    now = datetime.now(UTC)
    active = snapshot_factory("active").model_copy(update={"updated_at": now})
    archived = snapshot_factory("archived", archived=True).model_copy(
        update={"updated_at": now - timedelta(days=120)}
    )
    old_active = snapshot_factory("old-active").model_copy(
        update={"updated_at": now - timedelta(days=100)}
    )
    window.task_snapshots = (active, archived, old_active)
    window._all_task_snapshots = window.task_snapshots

    window._populate_task_list(window.task_snapshots)
    assert set(window._visible_task_ids()) == {"active", "old-active"}
    assert window.ui.taskFilterButton.text() == "筛选"
    assert [action.text() for action in window.ui.taskFilterButton.menu().actions()] == [
        "天数 > N 天",
        "全部",
        "活跃",
        "已归档",
    ]

    window._set_task_filter("all")
    assert set(window._visible_task_ids()) == {"active", "archived", "old-active"}
    window._set_task_filter("archived")
    assert window._visible_task_ids() == ("archived",)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_args, **_kwargs: (90, True))
    window._set_task_filter("older")
    assert set(window._visible_task_ids()) == {"archived", "old-active"}


def test_task_header_selects_only_currently_filtered_tasks(
    qtbot, app_paths, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    active = snapshot_factory("active")
    archived = snapshot_factory("archived", archived=True)
    window.task_snapshots = (active, archived)
    window._all_task_snapshots = window.task_snapshots
    window._populate_task_list(window.task_snapshots)

    window._task_select_all_checkbox.setCheckState(Qt.CheckState.Checked)
    assert window._selected_task_ids() == ("active",)
    assert window.ui.taskListView.headerItem().checkState(0) is Qt.CheckState.Checked

    window._task_select_all_checkbox.setCheckState(Qt.CheckState.Unchecked)
    assert window._selected_task_ids() == ()
    assert window.ui.taskListView.headerItem().checkState(0) is Qt.CheckState.Unchecked


def test_task_checkboxes_drive_batch_selection_and_header_state(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    first = snapshot_factory("first")
    second = snapshot_factory("second")
    window.task_snapshots = (first, second)
    window._all_task_snapshots = window.task_snapshots
    window._task_capabilities = capabilities
    window._populate_task_list(window.task_snapshots)
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    items = {
        group.child(index).data(0, Qt.ItemDataRole.UserRole): group.child(index)
        for index in range(group.childCount())
    }
    first_item = items["first"]
    second_item = items["second"]
    assert first_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert second_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert first_item.data(0, Qt.ItemDataRole.CheckStateRole) is not None
    assert second_item.data(0, Qt.ItemDataRole.CheckStateRole) is not None

    first_item.setCheckState(0, Qt.CheckState.Checked)
    second_item.setCheckState(0, Qt.CheckState.Checked)
    assert set(window._selected_task_ids()) == {"first", "second"}
    assert window._task_select_all_checkbox.checkState() is Qt.CheckState.Checked
    assert window.ui.taskArchiveButton.isEnabled()

    first_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert window._selected_task_ids() == ("second",)
    assert window._task_select_all_checkbox.checkState() is Qt.CheckState.PartiallyChecked


def test_task_row_selection_checks_the_task(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    snapshot = snapshot_factory("selected")
    window.task_snapshots = (snapshot,)
    window._all_task_snapshots = window.task_snapshots
    window._task_capabilities = capabilities
    window._populate_task_list(window.task_snapshots)
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    item = group.child(0)
    assert item is not None

    window.ui.taskListView.setCurrentItem(item)

    assert item.checkState(0) is Qt.CheckState.Checked
    assert window._selected_task_ids() == ("selected",)
    assert window.ui.taskArchiveButton.isEnabled()


def test_task_checkbox_states_have_visible_light_theme_contrast(qtbot, app_paths) -> None:
    application = QApplication.instance()
    assert application is not None
    previous_stylesheet = application.styleSheet()
    application.setStyleSheet(previous_stylesheet + APP_STYLESHEET)
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    try:
        qtbot.addWidget(window)
        window.show()
        qtbot.wait(10)
        checkbox = window._task_select_all_checkbox
        unchecked = checkbox.grab().toImage()
        unchecked_colors = {
            unchecked.pixelColor(x, y).name()
            for x in range(unchecked.width())
            for y in range(unchecked.height())
        }

        checkbox.blockSignals(True)
        checkbox.setCheckState(Qt.CheckState.Checked)
        checked = checkbox.grab().toImage()
        checkbox.blockSignals(False)
        checked_colors = {
            checked.pixelColor(x, y).name()
            for x in range(checked.width())
            for y in range(checked.height())
        }

        assert OUTLINE_STRONG in unchecked_colors
        assert ACCENT in checked_colors
    finally:
        application.setStyleSheet(previous_stylesheet)


def test_footer_action_buttons_are_equal_fixed_width_and_right_aligned(qtbot, app_paths) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    buttons = tuple(
        window.ui.buttonLayout.itemAt(index).widget()
        for index in range(window.ui.buttonLayout.count())
    )
    assert buttons
    assert {button.minimumWidth() for button in buttons} == {136}
    assert {button.maximumWidth() for button in buttons} == {136}
    assert window.ui.buttonLayout.alignment() & Qt.AlignmentFlag.AlignRight
    assert window.ui.footerMainLayout.stretch(1) == 1
    assert window.ui.footerMainLayout.stretch(2) == 1


def test_trim_apply_button_requires_safe_inactive_source_status(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    not_loaded = _document(
        snapshot_factory("not-loaded", status=ThreadStatus.NOT_LOADED), capabilities
    )
    window._document_loaded(0, not_loaded)
    assert not window.ui.applyButton.isEnabled()
    assert "当前仅支持审查与投影计划" in window.ui.applyButton.toolTip()

    unknown = _document(snapshot_factory("unknown", status=ThreadStatus.UNKNOWN), capabilities)
    window._document_loaded(0, unknown)
    assert not window.ui.applyButton.isEnabled()


def test_task_pane_toggle_expands_center_and_preserves_action_width(qtbot, app_paths) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)

    splitter = window.ui.mainSplitter
    expanded_sizes = splitter.sizes()
    action_width = expanded_sizes[-1]
    window._toggle_task_pane()
    qtbot.wait(10)
    collapsed_sizes = splitter.sizes()

    assert not window.ui.taskPane.isVisible()
    assert window.ui.toolRail.isVisible()
    assert window.ui.projectTaskRailButton.isChecked()
    assert not window.ui.taskPaneCollapseButton.isVisible()
    assert collapsed_sizes[0] == 0
    assert collapsed_sizes[1] > expanded_sizes[1]
    assert collapsed_sizes[2] > expanded_sizes[2]
    assert collapsed_sizes[-1] == action_width

    window._toggle_task_pane()
    qtbot.wait(10)
    assert window.ui.taskPane.isVisible()
    assert window.ui.projectTaskRailButton.isChecked()
    assert window.ui.taskPaneCollapseButton.isVisible()
    assert splitter.sizes() == expanded_sizes


def test_review_window_minimum_size_keeps_splitter_panes_non_overlapping(qtbot, app_paths) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.wait(10)

    splitter = window.ui.mainSplitter
    panes = (
        window.ui.taskPane,
        window.ui.timelinePane,
        window.ui.contentPane,
        window.ui.actionPane,
    )
    sizes = splitter.sizes()

    assert (window.width(), window.height()) == (1280, 720)
    assert window.minimumSizeHint().width() <= 1280
    assert len(sizes) == len(panes)
    assert all(size >= pane.minimumWidth() for size, pane in zip(sizes, panes, strict=True))
    assert all(left.geometry().right() < right.geometry().left() for left, right in pairwise(panes))


def test_protected_gui_target_refuses_exclusion(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("protected")
    item = (
        snapshot.turns[0]
        .items[0]
        .model_copy(
            update={
                "hard_protected": True,
                "protected_reasons": ("current user request",),
            }
        )
    )
    snapshot = snapshot.model_copy(
        update={"turns": (snapshot.turns[0].model_copy(update={"items": (item,)}),)}
    )
    document = _document(snapshot, capabilities)
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, document)
    window.current_target = snapshot.turns[0]
    window._show_target(snapshot.turns[0])
    window._action_changed(1)
    assert window.selections[snapshot.turns[0].id].action is TrimAction.KEEP
    assert "硬保护" in window.ui.errorLabel.text()


def test_task_list_selection_loads_selected_thread_id(qtbot, app_paths, snapshot_factory) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    snapshot = snapshot_factory("selected-task")
    window.task_snapshots = (snapshot,)
    window._populate_task_list(window.task_snapshots)

    loaded_ids: list[str] = []
    window.load_thread = loaded_ids.append  # type: ignore[method-assign]
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    item = group.child(0)
    assert item is not None
    window.ui.taskListView.setCurrentItem(item)
    window._task_clicked(item, 0)

    assert loaded_ids == ["selected-task"]
    assert window.ui.threadIdEdit.text() == ""


def test_archive_button_switches_to_unarchive_and_rejects_mixed_selection(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    archived = snapshot_factory("archived", archived=True)
    active = snapshot_factory("active")
    running = snapshot_factory("running", status=ThreadStatus.ACTIVE)
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.task_snapshots = (archived, active, running)
    window._all_task_snapshots = window.task_snapshots
    window._task_capabilities = capabilities
    window._set_task_filter("all")
    window._populate_task_list(window.task_snapshots)

    window._select_task_in_list("archived")
    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskArchiveButton.text() == "反归档"

    window._select_task_in_list("active")
    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskArchiveButton.text() == "归档"

    window._select_task_ids(("active", "archived"))
    assert not window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskArchiveButton.text() == "归档"

    window._select_task_in_list("running")
    assert not window.ui.taskArchiveButton.isEnabled()


def test_archive_button_accepts_safe_lightweight_inventory_summary(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    summary = snapshot_factory("summary", content_complete=False)
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.task_snapshots = (summary,)
    window._all_task_snapshots = window.task_snapshots
    window._task_capabilities = capabilities
    window._populate_task_list(window.task_snapshots)

    window._select_task_in_list("summary")

    assert window._selected_task_ids() == ("summary",)
    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskArchiveButton.text() == "归档"


def test_failed_task_operation_refreshes_inventory(qtbot, app_paths) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    refreshes: list[bool] = []
    window.load_task_list = lambda: refreshes.append(True)  # type: ignore[method-assign]
    window._task_write_in_progress = True

    window._finish_task_operation({"error": "write result is ambiguous"}, lambda _value: None)

    assert refreshes == [True]


def test_message_box_message_label_uses_application_text_color(qtbot) -> None:
    application = QApplication.instance()
    assert application is not None
    previous_stylesheet = application.styleSheet()
    application.setStyleSheet(previous_stylesheet + APP_STYLESHEET)
    message_box = QMessageBox()
    try:
        qtbot.addWidget(message_box)
        message_box.setText("高风险确认文本")
        message_box.show()
        qtbot.wait(10)

        message_label = next(
            label
            for label in message_box.findChildren(QLabel)
            if label.objectName() == "qt_msgbox_label"
        )
        assert message_label.palette().color(message_label.foregroundRole()).name() == TEXT
    finally:
        application.setStyleSheet(previous_stylesheet)


def test_input_dialog_label_uses_application_text_color(qtbot) -> None:
    application = QApplication.instance()
    assert application is not None
    previous_stylesheet = application.styleSheet()
    application.setStyleSheet(previous_stylesheet + APP_STYLESHEET)
    input_dialog = QInputDialog()
    try:
        qtbot.addWidget(input_dialog)
        input_dialog.setLabelText("输入确认文本")
        input_dialog.show()
        qtbot.wait(10)

        prompt_label = next(label for label in input_dialog.findChildren(QLabel) if label.text())
        assert prompt_label.palette().color(prompt_label.foregroundRole()).name() == TEXT
    finally:
        application.setStyleSheet(previous_stylesheet)


def test_shared_task_query_filters_and_supports_multi_selection(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    first = snapshot_factory("first").model_copy(update={"title": "Alpha conversation"})
    second = snapshot_factory("second").model_copy(update={"title": "Beta conversation"})
    window.task_snapshots = (first, second)
    window._all_task_snapshots = window.task_snapshots
    window._task_capabilities = capabilities
    window._populate_task_list(window.task_snapshots)
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None and group.childCount() == 2

    group.child(0).setSelected(True)
    group.child(1).setSelected(True)
    assert set(window._selected_task_ids()) == {"first", "second"}
    assert window.ui.taskBackupButton.isEnabled()
    assert window.ui.taskArchiveButton.isEnabled()
    window._populate_task_list(window.task_snapshots)
    assert set(window._selected_task_ids()) == {"first", "second"}

    window.ui.threadIdEdit.setText("Alpha")
    assert window.ui.taskListView.topLevelItem(0).childCount() == 1
    assert window.ui.taskListView.topLevelItem(0).child(0).text(0) == "Alpha conversation"


def test_incomplete_mapping_loads_timeline_as_read_only_review(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("read-only-review").model_copy(update={"mapping_complete": False})

    class FakeWorkflows:
        def read_thread(self, thread_id: str, *, include_turns: bool = True) -> ThreadReadResult:
            assert thread_id == snapshot.id
            assert include_turns
            return ThreadReadResult(capabilities, snapshot)

    window = TrimReviewWindow(
        paths=app_paths,
        workflows=FakeWorkflows(),  # type: ignore[arg-type]
        load_task_list=False,
    )
    qtbot.addWidget(window)

    window.load_thread(snapshot.id)
    qtbot.waitUntil(lambda: window.document is not None, timeout=2000)

    assert window.ui.timelineView.model().rowCount() == 1
    assert window.current_plan is None
    assert not window.ui.actionCombo.isEnabled()
    assert not window.ui.suggestButton.isEnabled()
    assert not window.ui.savePlanButton.isEnabled()
    assert not window.ui.applyButton.isEnabled()
    assert window.ui.contentBrowser.isReadOnly()
    assert "只读浏览" in window.ui.taskListStatusLabel.text()


def test_read_only_error_identifies_the_actual_codex_runtime(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("read-only-runtime")
    read_only = capabilities.model_copy(
        update={
            "codex_version": "0.151.0-alpha.7.2",
            "codex_binary_path": "/Applications/ChatGPT.app/Contents/Resources/codex",
            "schema_sha256": "7" * 64,
        }
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window._document_loaded(0, _document(snapshot, read_only))

    assert window.ui.errorLabel.isHidden()
    assert not window.ui.applyButton.isEnabled()
    assert "当前仅支持审查与投影计划" in window.ui.applyButton.toolTip()


def test_gui_backup_request_uses_managed_identity_and_expands_descendants(qtbot, app_paths) -> None:
    manifest = BackupManifest(
        backup_id="backup-id",
        created_at=utc_now(),
        tool_version="test",
        encryption="age-recipient",
        entries=(),
        source_fingerprints={},
    ).seal()
    expected = BackupCreationResult(manifest, ("child", "root"))

    class FakeWorkflows:
        def __init__(self) -> None:
            self.call = None

        def create_managed_backup(self, destination, **kwargs):
            self.call = (destination, kwargs)
            return expected

    workflows = FakeWorkflows()
    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=workflows,  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    destination = app_paths.backups_dir / "selected.csmbackup"

    result = window._create_selected_backup(
        ("root",),
        destination,
    )

    assert result is expected
    assert workflows.call is not None
    called_destination, kwargs = workflows.call
    assert called_destination == destination
    assert kwargs["thread_ids"] == ("root",)
    assert kwargs["include_raw"] is True
    assert kwargs["expand_descendants"] is True


def test_gui_backup_settings_auto_selects_managed_identity(
    qtbot, app_paths, snapshot_factory, monkeypatch
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    root = snapshot_factory("root").model_copy(update={"spawned_descendant_ids": ("child",)})
    child = snapshot_factory("child", parent_id="root")
    window._all_task_snapshots = (root, child)
    destination = app_paths.backups_dir / "selected.csmbackup"
    questions: list[str] = []

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), ""),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("managed backup must not ask for an identity file")
        ),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("managed backup must not ask for a recipient")
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args, **_kwargs: (
            questions.append(message) or QMessageBox.StandardButton.Yes
        ),
    )

    settings = window._request_backup_settings(("root",))

    assert settings == destination
    assert len(questions) == 2
    assert "root" in questions[-1]
    assert "child" in questions[-1]


def test_gui_verified_backup_completion_keeps_archive_as_separate_step(
    qtbot, app_paths, monkeypatch
) -> None:
    manifest = BackupManifest(
        backup_id="backup-id",
        created_at=utc_now(),
        tool_version="test",
        encryption="age-recipient",
        entries=(),
        source_fingerprints={},
    ).seal()
    result = BackupCreationResult(manifest, ("root", "child"))
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message: messages.append(message),
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window._task_backup_succeeded(result)

    assert messages and manifest.manifest_sha256 in messages[0]
    assert "归档计划" in messages[0]
    assert "已覆盖 2 个对话" in window.ui.taskListStatusLabel.text()


def test_task_list_groups_same_project_and_shows_relative_activity(
    qtbot, app_paths, snapshot_factory
) -> None:
    now = datetime.now(UTC)
    first = snapshot_factory("first", updated_at=now - timedelta(days=2))
    second = snapshot_factory("second", updated_at=now - timedelta(days=5))
    other = snapshot_factory("other", updated_at=now - timedelta(days=1)).model_copy(
        update={"cwd": "/tmp/another-project"}
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window.task_snapshots = (first, second, other)
    window._populate_task_list(window.task_snapshots)

    assert window.ui.taskListView.topLevelItemCount() == 2
    project_group = next(
        window.ui.taskListView.topLevelItem(index)
        for index in range(window.ui.taskListView.topLevelItemCount())
        if window.ui.taskListView.topLevelItem(index).text(0) == "project"
    )
    assert project_group.childCount() == 2
    assert project_group.child(0).text(1).endswith("天前")
    assert first.id not in project_group.child(0).text(1)
    assert first.id in project_group.child(0).toolTip(1)


def test_sensitive_filter_shows_only_redacted_local_matches(
    qtbot, app_paths, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    matched = snapshot_factory("matched")
    clean = snapshot_factory("clean")
    window.task_snapshots = (matched, clean)
    window._sensitive_matches = {
        "matched": SensitiveScanResult((SensitiveFinding("API 密钥", SensitiveSeverity.HIGH, 1),))
    }
    window._sensitive_scan_complete = True

    window.ui.sensitiveScanButton.click()

    assert window.ui.taskListView.topLevelItem(0).childCount() == 1
    item = window.ui.taskListView.topLevelItem(0).child(0)
    assert item.data(0, Qt.ItemDataRole.UserRole) == "matched"
    assert "API 密钥×1" in item.toolTip(0)
    assert "疑似敏感" in window.ui.taskListStatusLabel.text()


def test_sensitive_filter_highlights_exact_context_ranges(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    secret = "sk-proj-1234567890abcdefghijkl"
    snapshot = snapshot_factory(
        "sensitive-content",
        turns=(
            TurnSnapshot(
                id="turn-1",
                status="completed",
                items=(
                    ThreadItemSnapshot(
                        id="message-1",
                        turn_id="turn-1",
                        kind=ItemKind.USER_MESSAGE,
                        raw_type="userMessage",
                        role="user",
                        text=f"safe prefix\napi_key={secret}\nsafe suffix",
                        token_estimate=12,
                    ),
                ),
            ),
        ),
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot, capabilities))
    window.current_target = snapshot.turns[0].items[0]
    window._show_target(window.current_target)

    window.ui.sensitiveScanButton.blockSignals(True)
    window.ui.sensitiveScanButton.setChecked(True)
    window.ui.sensitiveScanButton.blockSignals(False)
    window._apply_content_overlays()

    highlighted = [
        selection
        for selection in window.ui.contentBrowser.extraSelections()
        if selection.format.background().color().name() == DANGER
    ]
    assert any(secret in selection.cursor.selectedText() for selection in highlighted)
    assert all(
        selection.format.foreground().color().name() == "#ffffff" for selection in highlighted
    )

    window.ui.contentMarkdownButton.click()
    markdown_highlighted = [
        selection
        for selection in window.ui.contentBrowser.extraSelections()
        if selection.format.background().color().name() == DANGER
    ]
    assert any(secret in selection.cursor.selectedText() for selection in markdown_highlighted)


def test_sensitive_scan_uses_window_modal_progress_dialog_and_worker(
    qtbot, app_paths, snapshot_factory
) -> None:
    observed_values: list[int] = []

    class Workflows:
        def scan_sensitive_threads(self, thread_ids, *, cancelled, progress):
            assert thread_ids == ("matched", "clean")
            assert not cancelled()
            progress((1, 2))
            assert window._sensitive_progress_dialog is not None
            observed_values.append(window._sensitive_progress_dialog.value())
            progress((2, 2))
            assert window._sensitive_progress_dialog is not None
            observed_values.append(window._sensitive_progress_dialog.value())
            match = SensitiveScanResult(
                (SensitiveFinding("云服务/API 密钥", SensitiveSeverity.HIGH, 1),)
            )
            return SensitiveScanBatch({"matched": match}, scanned=2, failed=0)

    class CapturingPool:
        worker = None

        def start(self, worker) -> None:
            self.worker = worker

    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=Workflows(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.task_snapshots = (snapshot_factory("matched"), snapshot_factory("clean"))
    window._populate_task_list(window.task_snapshots)
    pool = CapturingPool()
    window.thread_pool = pool  # type: ignore[assignment]
    window.show()

    window.ui.sensitiveScanButton.click()

    dialog = window._sensitive_progress_dialog
    assert isinstance(dialog, QProgressDialog)
    assert dialog.windowModality() is Qt.WindowModality.WindowModal
    assert dialog.minimum() == 0
    assert dialog.maximum() == 2
    assert dialog.value() == 0
    assert dialog.isVisible()
    assert pool.worker is not None

    pool.worker.run()

    assert observed_values == [1, 2]
    assert window._sensitive_progress_dialog is None
    assert window._sensitive_scan_complete
    assert "1 个疑似敏感对话" in window.ui.taskListStatusLabel.text()


def test_sensitive_scan_progress_cancel_unchecks_filter(qtbot, app_paths, snapshot_factory) -> None:
    class Workflows:
        def scan_sensitive_threads(self, _thread_ids, *, cancelled, progress):
            raise AssertionError("captured worker should not run after cancellation")

    class CapturingPool:
        worker = None

        def start(self, worker) -> None:
            self.worker = worker

    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=Workflows(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.task_snapshots = (snapshot_factory("one"),)
    pool = CapturingPool()
    window.thread_pool = pool  # type: ignore[assignment]

    window.ui.sensitiveScanButton.click()
    dialog = window._sensitive_progress_dialog
    assert dialog is not None

    dialog.canceled.emit()

    assert not window.ui.sensitiveScanButton.isChecked()
    assert window._sensitive_progress_dialog is None
    assert "已关闭" in window.ui.taskListStatusLabel.text()


def test_sensitive_scan_keeps_qt_event_loop_responsive_during_large_regex_work(
    qtbot, app_paths, snapshot_factory
) -> None:
    large_snapshot = snapshot_factory(
        "large-sensitive-scan",
        turns=(
            TurnSnapshot(
                id="turn-1",
                status="completed",
                items=(
                    ThreadItemSnapshot(
                        id="large-item",
                        turn_id="turn-1",
                        kind=ItemKind.USER_MESSAGE,
                        raw_type="userMessage",
                        role="user",
                        text="1234 5678 9012 3456 789\n" * (8 * 1024 * 1024 // 25),
                        token_estimate=1,
                    ),
                ),
            ),
        ),
    ).model_copy(update={"title": "", "preview": ""})
    started = threading.Event()
    finished = threading.Event()

    class Workflows:
        def scan_sensitive_threads(self, _thread_ids, *, cancelled, progress):
            started.set()
            result = scan_sensitive_snapshot(large_snapshot, cancelled=cancelled)
            progress((1, 1))
            finished.set()
            return SensitiveScanBatch(
                {large_snapshot.id: result} if result.has_findings else {},
                scanned=1,
                failed=0,
            )

    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=Workflows(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.task_snapshots = (snapshot_factory("large-sensitive-scan"),)
    window.show()

    heartbeat_during_scan: list[bool] = []

    def heartbeat() -> None:
        if started.is_set() and not finished.is_set():
            heartbeat_during_scan.append(True)
            return
        if not finished.is_set():
            QTimer.singleShot(5, heartbeat)

    QTimer.singleShot(5, heartbeat)
    window.ui.sensitiveScanButton.click()

    qtbot.waitUntil(started.is_set, timeout=1_000)
    qtbot.waitUntil(lambda: bool(heartbeat_during_scan), timeout=1_000)
    qtbot.waitUntil(finished.is_set, timeout=5_000)
    qtbot.waitUntil(lambda: window._sensitive_progress_dialog is None, timeout=1_000)

    assert heartbeat_during_scan == [True]


def test_timeline_hides_all_empty_zero_token_items_and_summarizes_usage(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory(
        "filtered",
        turns=(
            TurnSnapshot(
                id="turn-1",
                status="completed",
                items=(
                    ThreadItemSnapshot(
                        id="reasoning-empty",
                        turn_id="turn-1",
                        kind=ItemKind.REASONING,
                        raw_type="reasoning",
                    ),
                    ThreadItemSnapshot(
                        id="unknown-empty",
                        turn_id="turn-1",
                        kind=ItemKind.UNKNOWN,
                        raw_type="futureItem",
                    ),
                    ThreadItemSnapshot(
                        id="file-change-empty",
                        turn_id="turn-1",
                        kind=ItemKind.FILE_CHANGE,
                        raw_type="fileChange",
                    ),
                    ThreadItemSnapshot(
                        id="user-visible",
                        turn_id="turn-1",
                        kind=ItemKind.USER_MESSAGE,
                        raw_type="userMessage",
                        role="user",
                        text="question",
                        token_estimate=4,
                    ),
                    ThreadItemSnapshot(
                        id="assistant-visible",
                        turn_id="turn-1",
                        kind=ItemKind.ASSISTANT_MESSAGE,
                        raw_type="agentMessage",
                        role="assistant",
                        text="visible",
                        token_estimate=2,
                    ),
                ),
            ),
        ),
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot, capabilities))

    model = window.ui.timelineView.model()
    assert model.hidden_internal_item_count == 3
    assert model.rowCount(model.index(0, 0)) == 2
    assert window.ui.timelineHelp.text() == "隐藏 3 · 输入 4 · 输出 2"


def test_content_editor_tags_and_markdown_controls(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory(
        "content",
        turns=(
            TurnSnapshot(
                id="turn-1",
                status="completed",
                items=(
                    ThreadItemSnapshot(
                        id="message-1",
                        turn_id="turn-1",
                        kind=ItemKind.USER_MESSAGE,
                        raw_type="userMessage",
                        role="user",
                        text=(
                            '<codex_delegation source="a > b">\n'
                            "<source_thread_id>source-1</source_thread_id>\n"
                            "&lt;input&gt;**draft**&lt;/input&gt;\n"
                            "</codex_delegation>\n"
                            "<payload>tail</payload>"
                        ),
                        token_estimate=3,
                    ),
                ),
            ),
        ),
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot, capabilities))
    window.current_target = snapshot.turns[0].items[0]
    window._show_target(snapshot.turns[0].items[0])

    assert not window.ui.contentTagsButton.isChecked()
    assert not window.ui.contentMarkdownButton.isChecked()
    assert not window.ui.contentBrowser.isReadOnly()
    assert window.ui.contentBrowser.toPlainText().startswith("<codex_delegation")
    assert len(window.ui.contentBrowser.extraSelections()) >= 6
    cursor = window.ui.contentBrowser.textCursor()
    cursor.setPosition(12)
    window.ui.contentBrowser.setTextCursor(cursor)
    window.ui.contentTagsButton.click()
    assert window.ui.contentBrowser.textCursor().position() == 12
    window.ui.contentTagsButton.click()
    assert window.ui.contentBrowser.textCursor().position() == 12
    window.ui.contentMarkdownButton.click()
    assert "codex_delegation" not in window.ui.contentBrowser.toPlainText()
    assert "draft" in window.ui.contentBrowser.toPlainText()
    window.ui.contentMarkdownButton.click()
    assert window.ui.contentBrowser.textCursor().position() == 12
    window.selections["turn-1"] = TrimSelection(
        target_id="turn-1",
        action=TrimAction.SUMMARY,
        summary="old whole-turn summary",
    )
    window.ui.contentBrowser.setPlainText("edited")
    assert window._content_drafts["message-1"] == "edited"
    assert window.selections["turn-1"].action is TrimAction.KEEP
    assert window.selections["message-1"].action is TrimAction.SUMMARY
    assert window.selections["message-1"].summary == "edited"

    # Repeated editing is a regression guard for the previous implementation,
    # which recursively mutated QTextDocument formatting from textChanged and
    # could crash the packaged app while the user typed.
    for index in range(100):
        window.ui.contentBrowser.setPlainText(f'edited {index}\n<foo attr="x">body</foo>')
        qtbot.wait(0)
    assert window._content_drafts["message-1"].startswith("edited 99")

    window.ui.contentTagsButton.click()
    assert window.ui.contentTagsButton.isChecked()
    assert window.ui.contentBrowser.toPlainText().startswith("edited 99")
    window.ui.contentMarkdownButton.click()
    assert window.ui.contentMarkdownButton.isChecked()
    assert window.ui.contentBrowser.isReadOnly()
    assert '<foo attr="x">' in window.ui.contentBrowser.toPlainText()
    window.ui.contentMarkdownButton.click()
    assert not window.ui.contentBrowser.isReadOnly()


def test_compact_timeline_numbers_and_runtime_language_switch(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    assert not missing_translation_keys(GuiLanguage.EN_US)
    assert compact_number(999) == "999"
    assert compact_number(1_000) == "1k"
    assert compact_number(91_629) == "91.6k"
    assert compact_number(1_500_000) == "1.5m"

    snapshot = snapshot_factory(
        "translated",
        turns=(
            TurnSnapshot(
                id="turn-large",
                status="completed",
                items=(
                    ThreadItemSnapshot(
                        id="large-1",
                        turn_id="turn-large",
                        kind=ItemKind.USER_MESSAGE,
                        raw_type="userMessage",
                        role="user",
                        text="large input",
                        token_estimate=91_629,
                    ),
                    ThreadItemSnapshot(
                        id="large-2",
                        turn_id="turn-large",
                        kind=ItemKind.ASSISTANT_MESSAGE,
                        raw_type="agentMessage",
                        role="assistant",
                        text="large output",
                        token_estimate=1_500_000,
                    ),
                ),
            ),
        ),
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot, capabilities))

    assert window.ui.languageCombo.currentText() == "中文"
    assert window.ui.savePlanButton.text() == "保存方案"
    model = window.ui.timelineView.model()
    turn_index = model.index(0, 0, QModelIndex())
    assert model.data(model.index(0, 2, QModelIndex())) == "1.6m"
    assert model.data(model.index(0, 2, turn_index)) == "91.6k"
    assert model.data(model.index(1, 2, turn_index)) == "1.5m"
    assert window.ui.tokenLabel.text() == "预计上下文：1.6m → 1.6m tokens（节省约 0）"
    window.ui.languageCombo.setCurrentIndex(1)
    assert (app_paths.config_dir / "gui-preferences.json").is_file()
    assert window.ui.headerBadge.text() == "Source task is read-only"
    assert window.ui.taskListView.headerItem().text(0).strip() == "Task"
    assert window.ui.timelineView.model().headerData(0, Qt.Orientation.Horizontal) == "Timeline"
    assert window.ui.contentTitle.text() == "Context"
    assert window.ui.savePlanButton.text() == "Save plan"
    assert window.ui.cancelButton.text() == "Close"
    assert window.ui.taskPaneCollapseButton.text() == "Collapse"
    assert window.ui.tokenLabel.text() == "Estimated context: 1.6m → 1.6m tokens (save about 0)"

    window.ui.languageCombo.setCurrentIndex(0)
    assert window.ui.headerBadge.text() == "原任务只读保护"
    assert window.ui.contentTitle.text() == "上下文"
    assert window.ui.savePlanButton.text() == "保存方案"
    assert window.ui.taskPaneCollapseButton.text() == "收起"


def test_precompact_prompt_can_render_persisted_english(qtbot) -> None:
    prompt = PrecompactPromptDialog(seconds=15, language=GuiLanguage.EN_US)
    qtbot.addWidget(prompt)

    assert prompt.windowTitle() == "Review context before compaction"
    assert prompt.ui.reviewButton.text() == "Review context…"
    assert prompt.ui.continueButton.text() == "Continue native compaction"


def test_all_panel_primary_controls_start_at_same_y(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot_factory("aligned"), capabilities))
    window.show()
    qtbot.wait(10)

    origin = QPoint(0, 0)
    control_top_edges = {
        widget.objectName(): widget.mapTo(window, origin).y()
        for widget in (
            window.ui.threadIdEdit,
            window.ui.timelineView,
            window.ui.contentBrowser,
            window.ui.actionCombo,
        )
    }
    assert len(set(control_top_edges.values())) == 1, control_top_edges
    assert window.ui.timelineView.height() == window.ui.contentBrowser.height()


def test_window_refuses_close_during_worker_write_and_ignores_late_completion(
    qtbot, app_paths
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._task_write_in_progress = True
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert not window._closing
    called: list[object] = []
    window._closing = True
    window._finish_task_operation({"value": object()}, called.append)
    assert called == []
    assert not window._task_write_in_progress


def test_plan_persistence_and_trim_apply_run_in_worker(
    qtbot, app_paths, capabilities, snapshot_factory, monkeypatch
) -> None:
    events: list[str] = []

    class Workflows:
        def save_plan(self, _plan: TrimPlan) -> Path:
            events.append("save")
            return app_paths.plans_dir / "plan.json"

        def apply_trim(self, _plan: TrimPlan) -> str:
            events.append("apply")
            return "derived"

    class CapturingPool:
        worker = None

        def start(self, worker) -> None:
            self.worker = worker

    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=Workflows(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window._document_loaded(0, _document(snapshot_factory("worker"), capabilities))
    pool = CapturingPool()
    window.thread_pool = pool  # type: ignore[assignment]

    window._save_plan()
    assert events == []
    assert window._write_in_progress
    assert pool.worker is not None
    pool.worker.run()
    assert events == ["save"]
    assert not window._write_in_progress
    assert window.current_plan is not None

    events.clear()
    saved_worker = pool.worker
    window._apply_plan()
    assert events == []
    assert not window._write_in_progress
    assert pool.worker is saved_worker


def test_designer_generated_modules_are_reproducible(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    pairs = (
        (
            root / "src/codex_session_manager/gui/main_window.ui",
            root / "src/codex_session_manager/gui/ui_main_window.py",
        ),
        (
            root / "src/codex_session_manager/gui/precompact_prompt.ui",
            root / "src/codex_session_manager/gui/ui_precompact_prompt.py",
        ),
    )
    for source, committed in pairs:
        generated = tmp_path / committed.name
        subprocess.run(
            [str(Path(sys.executable).with_name("pyside6-uic")), str(source), "-o", str(generated)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert generated.read_bytes() == committed.read_bytes()


def test_task_inventory_keeps_capabilities_for_archive_eligibility(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("inventory-capability")
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window._task_list_loaded(
        window._task_generation,
        InventoryResult(capabilities, (snapshot,)),
    )
    window._select_task_in_list(snapshot.id)

    assert window._task_capabilities is capabilities
    assert window.ui.taskArchiveButton.isEnabled()


def test_paginated_contract_reason_only_blocks_paginated_task(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    paginated = snapshot_factory(
        "paginated-contract",
        history_mode=ThreadHistoryMode.PAGINATED,
    )
    legacy = snapshot_factory("legacy-contract")
    blocked = _block_operation(
        capabilities,
        OperationName.HISTORY_PAGINATED,
        "ThreadTurnsListParams.itemsView must accept full",
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._task_list_loaded(
        window._task_generation,
        InventoryResult(blocked, (paginated, legacy)),
    )

    window._select_task_in_list(paginated.id)
    assert not window.ui.taskArchiveButton.isEnabled()
    assert "itemsView" in window.ui.taskArchiveButton.toolTip()

    window._select_task_in_list(legacy.id)
    assert window.ui.taskArchiveButton.isEnabled()


def test_archive_and_unarchive_contracts_are_independent_in_gui(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    archived = snapshot_factory("archived-contract", archived=True)
    blocked = _block_operation(capabilities, OperationName.ARCHIVE, "archive response mismatch")
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._set_task_filter("all")
    window._task_list_loaded(
        window._task_generation,
        InventoryResult(blocked, (archived,)),
    )

    window._select_task_in_list(archived.id)

    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskArchiveButton.text() == "反归档"


def test_unknown_history_mode_is_fail_closed_in_gui(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    unknown = snapshot_factory(
        "unknown-history",
        history_mode=ThreadHistoryMode.UNKNOWN,
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._task_list_loaded(
        window._task_generation,
        InventoryResult(capabilities, (unknown,)),
    )

    window._select_task_in_list(unknown.id)

    assert not window.ui.taskArchiveButton.isEnabled()
    assert "history mode is unknown" in window.ui.taskArchiveButton.toolTip()


def test_task_context_menu_has_no_rename_write_action(
    qtbot, app_paths, capabilities, snapshot_factory, monkeypatch
) -> None:
    snapshot = snapshot_factory("context-menu")
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._task_list_loaded(
        window._task_generation,
        InventoryResult(capabilities, (snapshot,)),
    )
    window.show()
    qtbot.wait(1)
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    item = group.child(0)

    class FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text
            self.triggered = FakeSignal()

        def text(self) -> str:
            return self._text

        def setEnabled(self, _enabled: bool) -> None:
            pass

    class FakeMenu:
        def __init__(self, _parent) -> None:
            self._actions: list[FakeAction] = []

        def addAction(self, text: str) -> FakeAction:
            action = FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self) -> None:
            pass

        def exec(self, *_args) -> None:
            pass

    menus: list[FakeMenu] = []
    original_menu = FakeMenu

    def make_menu(parent) -> FakeMenu:
        menu = original_menu(parent)
        menus.append(menu)
        return menu

    monkeypatch.setattr(controller_module, "QMenu", make_menu)

    window._show_task_context_menu(window.ui.taskListView.visualItemRect(item).center())

    assert menus
    assert all(action.text() != "更名…" for action in menus[0]._actions)


def test_context_plan_can_save_but_context_apply_stays_disabled(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window._document_loaded(0, _document(snapshot_factory("context-plan"), capabilities))

    assert window.ui.savePlanButton.isEnabled()
    assert not window.ui.applyButton.isEnabled()
    assert "当前仅支持审查与投影计划" in window.ui.applyButton.toolTip()
