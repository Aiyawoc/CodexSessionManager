from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView

from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection


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
    assert window.ui.footerFrame.maximumHeight() == 76
    assert window.ui.appTitleLabel.text() == "CodexSessionManager"
    assert window.ui.headerBadge.text() == "原任务只读保护"
    assert window.ui.errorLabel.isHidden()
    assert window.ui.taskListView.columnCount() == 3
    assert window.ui.threadIdEdit.parent() is window.ui.taskPane
    assert window.ui.taskContextStatusLabel.text() == "尚未加载任务"
    assert not window.ui.taskPaneCollapseButton.icon().isNull()
    assert window.ui.toolRail.minimumWidth() == 44
    assert window.ui.toolRail.maximumWidth() == 44
    assert window.ui.projectTaskRailButton.isChecked()

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

    assert loaded_ids == ["selected-task"]
    assert window.ui.threadIdEdit.text() == "selected-task"


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
