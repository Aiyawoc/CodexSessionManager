from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMessageBox

from codex_session_manager.backup import DecryptionSpec, EncryptionSpec
from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.gui.i18n import GuiLanguage, compact_number, missing_translation_keys
from codex_session_manager.gui.prompt import PrecompactPromptDialog
from codex_session_manager.gui.theme import APP_STYLESHEET, DANGER, SPLITTER_LINE
from codex_session_manager.gui.widgets import CenteredHandleSplitter
from codex_session_manager.hashing import utc_now
from codex_session_manager.models import (
    BackupManifest,
    ItemKind,
    ThreadItemSnapshot,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.sensitive import (
    SensitiveFinding,
    SensitiveScanResult,
    SensitiveSeverity,
)
from codex_session_manager.workflows import BackupCreationResult


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
    assert window.ui.threadIdEdit.parent() is window.ui.taskPane
    assert window.ui.taskContextStatusLabel.text() == "尚未加载任务"
    assert not hasattr(window.ui, "taskHelp")
    assert window.ui.taskPaneCollapseButton.text() == "收起"
    assert window.ui.taskBackupButton.text() == "备份并复验…"
    assert not window.ui.taskBackupButton.isEnabled()
    assert window.ui.taskPaneCollapseButton.icon().isNull()
    assert window.ui.toolRail.minimumWidth() == 44
    assert window.ui.toolRail.maximumWidth() == 44
    assert window.ui.toolRailLayout.count() == 2
    assert window.ui.projectTaskRailButton.isChecked()
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
    assert not window.ui.projectTaskRailButton.isChecked()
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


def test_shared_task_query_filters_and_supports_multi_selection(
    qtbot, app_paths, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    first = snapshot_factory("first").model_copy(update={"title": "Alpha conversation"})
    second = snapshot_factory("second").model_copy(update={"title": "Beta conversation"})
    window.task_snapshots = (first, second)
    window._populate_task_list(window.task_snapshots)
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None and group.childCount() == 2

    group.child(0).setSelected(True)
    group.child(1).setSelected(True)
    assert set(window._selected_task_ids()) == {"first", "second"}
    assert window.ui.taskBackupButton.isEnabled()
    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskDeleteButton.isEnabled()
    window._populate_task_list(window.task_snapshots)
    assert set(window._selected_task_ids()) == {"first", "second"}

    window.ui.threadIdEdit.setText("Alpha")
    assert window.ui.taskListView.topLevelItem(0).childCount() == 1
    assert window.ui.taskListView.topLevelItem(0).child(0).text(0) == "Alpha conversation"


def test_gui_backup_request_uses_recipient_identity_and_expands_descendants(
    qtbot, app_paths
) -> None:
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

        def create_backup(self, destination, **kwargs):
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
    identity = app_paths.data_dir / "identity.txt"

    result = window._create_selected_backup(
        ("root",),
        destination,
        "age1recipient",
        identity,
    )

    assert result is expected
    assert workflows.call is not None
    called_destination, kwargs = workflows.call
    assert called_destination == destination
    assert kwargs["thread_ids"] == ("root",)
    assert kwargs["encryption"] == EncryptionSpec(mode="age-recipient", recipient="age1recipient")
    assert kwargs["verification_decryption"] == DecryptionSpec(identity_file=identity)
    assert kwargs["include_raw"] is True
    assert kwargs["expand_descendants"] is True


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
    assert window.ui.taskListView.headerItem().text(0) == "Task"
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
    window._apply_plan()
    assert events == []
    assert window._write_in_progress
    assert pool.worker is not None
    pool.worker.run()
    assert events == ["save", "apply"]
    assert not window._write_in_progress


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
