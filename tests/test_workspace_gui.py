from __future__ import annotations

from PySide6.QtCore import Qt

from codex_session_manager.cleanup import CleanupPlanner
from codex_session_manager.gui.main_window import UnifiedMainWindow
from codex_session_manager.gui.single_instance import DesktopPage
from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection
from codex_session_manager.pending import PendingEntryKind, PendingPlanEntry
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


def test_unified_main_window_exposes_five_safe_workflow_entries(qtbot, app_paths) -> None:
    window = UnifiedMainWindow(app_paths)
    qtbot.addWidget(window)

    assert window.minimumWidth() == 1280
    assert window.minimumHeight() == 720
    assert window.navigation.count() == 5
    assert window.current_page is DesktopPage.CONTEXT
    assert [window.navigation.item(index).text() for index in range(5)] == [
        "对话清理",
        "上下文优化",
        "记忆管理",
        "待处理计划",
        "备份与恢复",
    ]

    for page in DesktopPage:
        window.open_page(page)
        assert window.current_page is page
        assert window.stack.currentWidget() is window._pages[page]


def test_cleanup_page_loads_suggestions_and_builds_plan_from_final_selection(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id="thread-1",
                source_fingerprint="a" * 64,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="长期未活动",
                confidence=0.9,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(app_paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(app_paths),
        target_ids=("thread-1",),
        suggestion_bundle_path=bundle_path,
    )
    window = UnifiedMainWindow(app_paths)
    qtbot.addWidget(window)

    window.load_request(request)

    assert window.current_page is DesktopPage.CLEANUP
    assert window.cleanup_page.selected_target_ids() == ("thread-1",)
    assert window.cleanup_page.create_plan_button.isEnabled()

    item = window.cleanup_page.tree.topLevelItem(0)
    assert item is not None
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert window.cleanup_page.selected_target_ids() == ()
    assert not window.cleanup_page.create_plan_button.isEnabled()

    snapshot = snapshot_factory("thread-1")
    plan = CleanupPlanner().plan_selected_archive(
        (snapshot,),
        capabilities,
        ("thread-1",),
    )
    selected: list[tuple[str, ...]] = []

    def build_plan(_request, selected_ids):
        selected.append(selected_ids)
        return plan

    window.cleanup_page.plan_builder = build_plan
    item.setCheckState(0, Qt.CheckState.Checked)
    with qtbot.waitSignal(window.cleanup_page.plan_created, timeout=1000) as emitted:
        qtbot.mouseClick(window.cleanup_page.create_plan_button, Qt.MouseButton.LeftButton)

    assert emitted.args == [plan]
    assert selected == [("thread-1",)]
    assert window.cleanup_page.current_plan == plan


def test_pending_page_routes_saved_trim_plan_back_to_context_review(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("thread-pending")
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
    PlanStore(app_paths).save(plan)
    window = UnifiedMainWindow(app_paths)
    qtbot.addWidget(window)
    window.open_page(DesktopPage.PENDING)

    assert window.pending_page.tree.topLevelItemCount() == 1
    item = window.pending_page.tree.topLevelItem(0)
    assert item is not None
    window.pending_page.tree.setCurrentItem(item)

    with qtbot.waitSignal(window.open_thread_requested, timeout=1000) as emitted:
        qtbot.mouseClick(window.pending_page.open_button, Qt.MouseButton.LeftButton)

    assert emitted.args == ["thread-pending"]


def test_pending_page_opens_only_rechecked_ready_hook_plan(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("thread-hook-pending")
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(TrimSelection(target_id=snapshot.turns[0].id, action=TrimAction.KEEP),),
        estimated_tokens_after=snapshot.token_estimate,
        trigger="hook",
    )
    plan_path = PlanStore(app_paths).save(plan)
    store = PendingTrimPlanStore(app_paths)
    waiting = PendingTrimPlan(
        plan_id=plan.plan_id,
        plan_path=str(plan_path),
        plan_sha256=plan.plan_sha256,
        source_thread_id=plan.source_thread_id,
        source_fingerprint=plan.source_thread_fingerprint,
        created_at=plan.created_at,
    )
    ready = store.transition(waiting, PendingPlanStatus.READY)
    assert ready.status is PendingPlanStatus.READY

    window = UnifiedMainWindow(app_paths)
    qtbot.addWidget(window)
    window.open_page(DesktopPage.PENDING)
    pending_item = next(
        window.pending_page.tree.topLevelItem(index)
        for index in range(window.pending_page.tree.topLevelItemCount())
        if PendingPlanEntry.model_validate(
            window.pending_page.tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
        ).kind
        is PendingEntryKind.PENDING_TRIM_PLAN
    )
    window.pending_page.tree.setCurrentItem(pending_item)

    with qtbot.waitSignal(window.open_pending_requested, timeout=1000) as emitted:
        qtbot.mouseClick(window.pending_page.open_button, Qt.MouseButton.LeftButton)

    assert emitted.args == [plan.plan_id]
