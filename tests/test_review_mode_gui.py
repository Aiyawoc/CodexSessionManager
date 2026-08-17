from __future__ import annotations

from PySide6.QtCore import Qt

from codex_session_manager.cleanup import CleanupPlanner
from codex_session_manager.gui import controller as controller_module
from codex_session_manager.gui.controller import TrimReviewWindow
from codex_session_manager.gui.review_mode import ReviewMode
from codex_session_manager.models import TrimAction
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewSource,
    SuggestedAction,
    SuggestionBundle,
    SuggestionBundleStore,
    SuggestionTarget,
    codex_account_fingerprint,
)
from codex_session_manager.workflows import ThreadReadResult


def test_memory_management_uses_second_button_in_original_gui(qtbot, app_paths) -> None:
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window._memory_paths = ("/tmp/project/MEMORY.md",)
    window.load_task_list = lambda: None  # type: ignore[method-assign]

    qtbot.mouseClick(window.ui.memoryRailButton, Qt.MouseButton.LeftButton)

    assert window.review_mode is ReviewMode.MEMORY_EDIT
    assert window.ui.memoryRailButton.isChecked()
    assert not window.ui.projectTaskRailButton.isChecked()
    assert window.ui.taskListView.topLevelItemCount() == 1
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    assert group.childCount() == 1
    assert group.child(0).data(0, Qt.ItemDataRole.UserRole) == "/tmp/project/MEMORY.md"
    assert window.ui.actionTitle.text() == "记忆动作"
    assert window.ui.contentBrowser.isReadOnly()

    qtbot.mouseClick(window.ui.projectTaskRailButton, Qt.MouseButton.LeftButton)

    assert window.review_mode is ReviewMode.CONTEXT_TRIM
    assert window.ui.projectTaskRailButton.isChecked()
    assert not window.ui.memoryRailButton.isChecked()


def test_cleanup_request_is_injected_into_original_project_list(
    qtbot, app_paths, snapshot_factory
) -> None:
    root = snapshot_factory("cleanup-root").model_copy(
        update={"spawned_descendant_ids": ("cleanup-child",)}
    )
    child = snapshot_factory("cleanup-child", parent_id="cleanup-root")
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=root.id,
                source_fingerprint=root.management_fingerprint,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="LLM 初筛：长期未活动且没有运行中的任务",
                confidence=0.86,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=(root.id,),
        suggestion_bundle_path=bundle_path,
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.load_task_list = lambda: None  # type: ignore[method-assign]

    window.load_review_request(request)
    window._task_list_loaded(window._task_generation, (root, child))

    assert window.review_mode is ReviewMode.CONVERSATION_CLEANUP
    assert window.property("csmReviewRequestId") == request.request_id
    assert window._selected_task_ids() == (root.id,)
    assert not window.ui.taskArchiveButton.isHidden()
    assert window.ui.taskArchiveButton.isEnabled()
    assert window.ui.taskDeleteButton.isHidden()
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    item = group.child(0)
    assert item.data(0, Qt.ItemDataRole.UserRole) == root.id
    assert "LLM 初筛" in item.toolTip(0)


def test_cleanup_mode_rebuilds_final_plan_through_sealed_review_request(
    qtbot, app_paths, capabilities, snapshot_factory, monkeypatch
) -> None:
    root = snapshot_factory("cleanup-plan-root")
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=root.id,
                source_fingerprint=root.management_fingerprint,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="LLM 初筛",
                confidence=0.8,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=(root.id,),
        suggestion_bundle_path=bundle_path,
    )
    expected = CleanupPlanner().plan_selected_archive(
        (root,),
        capabilities,
        (root.id,),
    )
    captured: list[tuple[ReviewRequest, tuple[str, ...]]] = []

    def rebuild(paths, received_request, selected_ids):
        assert paths == app_paths
        captured.append((received_request, selected_ids))
        return expected

    monkeypatch.setattr(controller_module, "prepare_cleanup_action_plan", rebuild)
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.load_task_list = lambda: None  # type: ignore[method-assign]
    window.load_review_request(request)

    plan = window._prepare_selected_archive((root.id,))

    assert plan == expected
    assert captured == [(request, (root.id,))]


def test_context_request_keeps_original_gui_and_stores_external_bundle(
    qtbot, app_paths, snapshot_factory
) -> None:
    snapshot = snapshot_factory("context-request")
    turn = snapshot.turns[0]
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=turn.id,
                source_fingerprint=turn.content_fingerprint,
                suggested_action=SuggestedAction.KEEP,
                reason="LLM 建议保留",
                confidence=0.9,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=(snapshot.id,),
        suggestion_bundle_path=bundle_path,
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    loaded: list[str] = []
    window.load_thread = loaded.append  # type: ignore[method-assign]

    window.load_review_request(request)

    assert window.review_mode is ReviewMode.CONTEXT_TRIM
    assert window.review_bundle == bundle
    assert loaded == [snapshot.id]
    assert not window.ui.savePlanButton.isHidden()


def test_context_request_injects_external_suggestions_into_original_timeline(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("context-injected")
    turn = snapshot.turns[0]
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=turn.id,
                source_fingerprint=turn.content_fingerprint,
                suggested_action=SuggestedAction.SUMMARY,
                suggested_text="注入原 GUI 的外部摘要",
                reason="LLM 初步筛查建议摘要",
                confidence=0.87,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=(snapshot.id,),
        suggestion_bundle_path=bundle_path,
    )

    class FakeWorkflows:
        def read_thread(self, thread_id: str, *, include_turns: bool = True) -> ThreadReadResult:
            assert thread_id == snapshot.id
            assert include_turns
            return ThreadReadResult(capabilities, snapshot)

    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        workflows=FakeWorkflows(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    window.load_review_request(request)
    qtbot.waitUntil(lambda: window.document is not None, timeout=2000)

    selection = window.selections[turn.id]
    assert selection.action is TrimAction.SUMMARY
    assert selection.summary == "注入原 GUI 的外部摘要"
    assert window.document is not None
    assert window.document.external_applied_target_ids == (turn.id,)
    assert "已灌入 1 条 LLM 建议" in window.ui.taskContextStatusLabel.text()
