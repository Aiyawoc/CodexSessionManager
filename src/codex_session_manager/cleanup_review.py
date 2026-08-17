"""Rebuild final cleanup plans from reviewed suggestions and current state."""

from __future__ import annotations

from pathlib import Path

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.cleanup import CleanupPlanner
from codex_session_manager.config import AppPaths
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import ActionPlan, CapabilityMatrix, ThreadSnapshot
from codex_session_manager.plans import PlanStore
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    SuggestedAction,
    SuggestionBundle,
    SuggestionBundleStore,
    codex_account_fingerprint,
)


def build_cleanup_action_plan(
    *,
    request: ReviewRequest,
    bundle: SuggestionBundle,
    selected_ids: tuple[str, ...],
    snapshots: tuple[ThreadSnapshot, ...],
    capabilities: CapabilityMatrix,
) -> ActionPlan:
    """Validate reviewed suggestions and build a new plan from current snapshots."""

    request.verify()
    bundle.verify()
    if request.operation is not ReviewOperation.CONVERSATION_CLEANUP:
        raise ValueError("cleanup review request has another operation")
    if bundle.operation is not ReviewOperation.CONVERSATION_CLEANUP:
        raise ValueError("cleanup suggestion bundle has another operation")
    if not selected_ids:
        raise ValueError("at least one cleanup suggestion must remain selected")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("selected cleanup ids must be unique")

    requested_ids = set(request.target_ids)
    if not set(selected_ids) <= requested_ids:
        raise ValueError("selected cleanup target is outside the review request")

    suggestions = {
        target.target_id: target for target in bundle.targets if target.target_id is not None
    }
    current = {snapshot.id: snapshot for snapshot in snapshots}
    for thread_id in selected_ids:
        suggestion = suggestions.get(thread_id)
        if suggestion is None:
            raise ValueError(f"selected cleanup target lacks a sealed suggestion: {thread_id}")
        if suggestion.suggested_action is not SuggestedAction.ARCHIVE:
            raise ValueError(f"selected cleanup target is not an archive suggestion: {thread_id}")
        snapshot = current.get(thread_id)
        if snapshot is None:
            raise ValueError(f"selected cleanup target no longer exists: {thread_id}")
        if snapshot.management_fingerprint != suggestion.source_fingerprint:
            raise ValueError(f"cleanup suggestion is stale for target: {thread_id}")

    return CleanupPlanner().plan_selected_archive(
        snapshots,
        capabilities,
        selected_ids,
    )


def prepare_cleanup_action_plan(
    paths: AppPaths,
    request: ReviewRequest,
    selected_ids: tuple[str, ...],
) -> ActionPlan:
    """Re-read App Server state, rebuild a sealed plan, and persist it privately."""

    if request.account_root_fingerprint != codex_account_fingerprint(paths):
        raise ValueError("cleanup review request is bound to another Codex account root")
    if not request.suggestion_bundle_path:
        raise ValueError("cleanup review request lacks a suggestion bundle")
    bundle = SuggestionBundleStore(paths).load(Path(request.suggestion_bundle_path))

    client, capabilities = connect_and_probe(request_timeout=45)
    try:
        snapshots = InventoryService(client).list(
            include_active=True,
            include_archived=True,
            include_turns=True,
        )
        plan = build_cleanup_action_plan(
            request=request,
            bundle=bundle,
            selected_ids=selected_ids,
            snapshots=snapshots,
            capabilities=capabilities,
        )
        PlanStore(paths).save(plan)
        return plan
    finally:
        client.close()
