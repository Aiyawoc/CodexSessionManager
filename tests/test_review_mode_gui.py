from __future__ import annotations

from PySide6.QtCore import Qt

from codex_session_manager.cleanup import CleanupPlanner
from codex_session_manager.gui import controller as controller_module
from codex_session_manager.gui.controller import TrimReviewWindow
from codex_session_manager.gui.review_mode import ReviewMode
from codex_session_manager.memory import MemoryAction, MemoryService, MemorySourceRegistry
from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection
from codex_session_manager.pending_plans import (
    PendingPlanStatus,
    PendingTrimPlan,
    PendingTrimPlanStore,
)
from codex_session_manager.plans import PlanStore
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
from codex_session_manager.workflows import CleanupCandidateInventory, ThreadReadResult


def test_memory_management_uses_second_button_in_original_gui(qtbot, app_paths, tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    memory_path = root / "MEMORY.md"
    memory_path.write_text("# Profile\n\nLikes tea.\n", encoding="utf-8")
    source = MemorySourceRegistry(app_paths).register(
        file_path=memory_path,
        root_path=root,
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)
    window.load_task_list = lambda: None  # type: ignore[method-assign]

    qtbot.mouseClick(window.ui.memoryRailButton, Qt.MouseButton.LeftButton)

    assert window.review_mode is ReviewMode.MEMORY_EDIT
    assert window.ui.memoryRailButton.isChecked()
    assert not window.ui.projectTaskRailButton.isChecked()
    assert window.ui.taskListView.topLevelItemCount() == 1
    group = window.ui.taskListView.topLevelItem(0)
    assert group is not None
    assert group.childCount() == 1
    assert group.child(0).data(0, Qt.ItemDataRole.UserRole) == source.source_id
    assert window.ui.actionTitle.text() == "记忆动作"
    assert window.ui.contentBrowser.isReadOnly()
    assert window.memory_snapshot is not None
    assert window.memory_timeline_model is not None
    assert window.memory_timeline_model.rowCount() >= 3
    assert not window.ui.savePlanButton.isEnabled()
    assert not window.ui.applyButton.isEnabled()

    qtbot.mouseClick(window.ui.projectTaskRailButton, Qt.MouseButton.LeftButton)

    assert window.review_mode is ReviewMode.CONTEXT_TRIM
    assert window.ui.projectTaskRailButton.isChecked()
    assert not window.ui.memoryRailButton.isChecked()


def test_memory_gui_action_uses_plan_backup_and_atomic_apply(
    qtbot, app_paths, tmp_path, monkeypatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    memory_path = root / "MEMORY.md"
    memory_path.write_text("# Profile\n\nLikes tea.\n", encoding="utf-8")
    MemorySourceRegistry(app_paths).register(file_path=memory_path, root_path=root)
    window = TrimReviewWindow(
        paths=app_paths,
        load_task_list=False,
        mode=ReviewMode.MEMORY_EDIT,
    )
    qtbot.addWidget(window)
    assert window.memory_snapshot is not None
    assert window.memory_timeline_model is not None
    paragraph_row = next(
        index
        for index, segment in enumerate(window.memory_snapshot.segments)
        if "Likes tea" in segment.text
    )
    window.ui.timelineView.setCurrentIndex(window.memory_timeline_model.index(paragraph_row, 0))
    qtbot.wait(1)
    window.ui.actionCombo.setCurrentIndex(2)
    window.ui.summaryEdit.setPlainText("Likes green tea.")
    assert (
        window.memory_selections[window.memory_snapshot.segments[paragraph_row].segment_id].action
        is MemoryAction.REPLACE
    )
    assert window.ui.savePlanButton.isEnabled()
    assert window.ui.applyButton.isEnabled()

    monkeypatch.setattr(
        controller_module.QMessageBox,
        "exec",
        lambda _self: controller_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        controller_module.QMessageBox,
        "information",
        lambda *_args, **_kwargs: controller_module.QMessageBox.StandardButton.Ok,
    )
    window._apply_memory_plan()

    assert memory_path.read_text(encoding="utf-8").endswith("Likes green tea.\n")
    assert len(window.memory_service.history(window.memory_snapshot.source_id)) == 1


def test_memory_request_injects_llm_suggestions_with_local_protection_veto(
    qtbot, app_paths, tmp_path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    memory_path = root / "MEMORY.md"
    memory_path.write_text("# Profile\n\nLikes tea.\n", encoding="utf-8")
    source = MemorySourceRegistry(app_paths).register(file_path=memory_path, root_path=root)
    snapshot = MemoryService(app_paths).snapshot(source.source_id)
    paragraph = next(segment for segment in snapshot.segments if "Likes tea" in segment.text)
    heading = next(segment for segment in snapshot.segments if segment.text.startswith("# "))
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.MEMORY_EDIT,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=paragraph.segment_id,
                source_fingerprint=paragraph.content_sha256,
                suggested_action=SuggestedAction.REPLACE,
                suggested_text="Likes green tea.",
                reason="LLM 初筛：偏好已更新",
                confidence=0.9,
            ),
            SuggestionTarget(
                target_id=heading.segment_id,
                source_fingerprint=heading.content_sha256,
                suggested_action=SuggestedAction.DELETE,
                reason="LLM 初筛：标题似乎冗余",
                confidence=0.6,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.MEMORY_EDIT,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_paths=(str(memory_path),),
        suggestion_bundle_path=bundle_path,
    )
    window = TrimReviewWindow(paths=app_paths, load_task_list=False)
    qtbot.addWidget(window)

    window.load_review_request(request)

    assert window.review_mode is ReviewMode.MEMORY_EDIT
    assert window.memory_selections[paragraph.segment_id].action is MemoryAction.REPLACE
    assert window.memory_selections[paragraph.segment_id].replacement == "Likes green tea."
    assert window.memory_selections[heading.segment_id].action is MemoryAction.PROTECT
    assert "已灌入 1 条 LLM 建议" in window.ui.taskContextStatusLabel.text()
    assert "1 条" in window.ui.taskContextStatusLabel.text()


def test_ready_pending_trim_plan_loads_exact_saved_selection_and_marks_applied(
    qtbot, app_paths, capabilities, snapshot_factory, monkeypatch
) -> None:
    snapshot = snapshot_factory("pending-review-thread")
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(
                target_id=snapshot.turns[0].id,
                action=TrimAction.KEEP,
            ),
        ),
        estimated_tokens_after=snapshot.token_estimate,
        trigger="hook",
    )
    plan_path = PlanStore(app_paths).save(plan)
    store = PendingTrimPlanStore(app_paths)
    ready = store.transition(
        PendingTrimPlan(
            plan_id=plan.plan_id,
            plan_path=str(plan_path),
            plan_sha256=plan.plan_sha256,
            source_thread_id=plan.source_thread_id,
            source_fingerprint=plan.source_thread_fingerprint,
            created_at=plan.created_at,
        ),
        PendingPlanStatus.READY,
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

    window.load_pending_trim_plan(ready)
    qtbot.waitUntil(lambda: window.document is not None, timeout=2000)

    assert window.current_plan == plan
    assert window.property("csmPendingTrimPlanId") == plan.plan_id
    assert window.selections[snapshot.turns[0].id].action is TrimAction.KEEP

    monkeypatch.setattr(
        controller_module.QMessageBox,
        "information",
        lambda *_args, **_kwargs: controller_module.QMessageBox.StandardButton.Ok,
    )
    window._apply_succeeded(window._generation, "derived-thread")

    assert store.load(store.path_for(plan.plan_id)).status is PendingPlanStatus.APPLIED


def test_cleanup_request_is_injected_into_original_project_list(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    root = snapshot_factory("cleanup-root").model_copy(
        update={"spawned_descendant_ids": ("cleanup-child",), "size_bytes": 2048}
    )
    child = snapshot_factory("cleanup-child", parent_id="cleanup-root").model_copy(
        update={"size_bytes": 1024}
    )
    supplemental = snapshot_factory("supplemental-root").model_copy(update={"size_bytes": 4096})
    purge = snapshot_factory("purge-root", archived=True).model_copy(update={"size_bytes": 8192})
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
    window._task_list_loaded(
        window._task_generation,
        CleanupCandidateInventory(
            capabilities,
            (root, child, supplemental, purge),
            frozenset({root.id}),
            (supplemental.id,),
            (purge.id,),
        ),
    )

    assert window.review_mode is ReviewMode.CONVERSATION_CLEANUP
    assert window.property("csmReviewRequestId") == request.request_id
    assert window._selected_task_ids() == (root.id,)
    assert window.ui.taskArchiveButton.isHidden()
    assert window.ui.taskBackupButton.text() == "备份并归档…"
    assert window.ui.taskBackupButton.isEnabled()
    assert window.ui.taskDeleteButton.isHidden()
    project_group = next(
        window.ui.taskListView.topLevelItem(index)
        for index in range(window.ui.taskListView.topLevelItemCount())
        if window.ui.taskListView.topLevelItem(index).text(0) == "project"
    )
    item = next(
        project_group.child(index)
        for index in range(project_group.childCount())
        if project_group.child(index).data(0, Qt.ItemDataRole.UserRole) == root.id
    )
    assert item.data(0, Qt.ItemDataRole.UserRole) == root.id
    assert "LLM 初筛" in item.toolTip(0)
    assert "当前有效备份：1/2" in item.toolTip(0)
    assert item.childCount() == 1
    descendant = item.child(0)
    assert descendant.text(0) == "↳ cleanup-child"
    assert not bool(descendant.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert "缺少当前指纹的有效备份" in descendant.toolTip(0)
    supplemental_item = next(
        project_group.child(index)
        for index in range(project_group.childCount())
        if project_group.child(index).data(0, Qt.ItemDataRole.UserRole) == supplemental.id
    )
    assert supplemental_item.text(0) == "＋ supplemental-root"
    assert not supplemental_item.isSelected()
    assert "默认不选中" in supplemental_item.toolTip(0)
    purge_group = next(
        window.ui.taskListView.topLevelItem(index)
        for index in range(window.ui.taskListView.topLevelItemCount())
        if window.ui.taskListView.topLevelItem(index).text(0).startswith("永久删除资格")
    )
    assert purge_group.childCount() == 1
    purge_item = purge_group.child(0)
    assert purge_item.text(0) == "高风险：purge-root"
    assert not bool(purge_item.flags() & Qt.ItemFlag.ItemIsSelectable)


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

    def rebuild(paths, received_request, selected_ids, *, allow_user_additions=False):
        assert paths == app_paths
        assert allow_user_additions
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
