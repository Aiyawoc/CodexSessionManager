from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_session_manager.app_server import RequestError, RequestTimeout
from codex_session_manager.audit import AuditStore
from codex_session_manager.cleanup import (
    CleanupExecutor,
    CleanupPlanner,
    CleanupPolicy,
    selected_root_block_reason,
)
from codex_session_manager.hashing import hash_file
from codex_session_manager.inventory import InventoryFilter, attach_descendant_closures
from codex_session_manager.models import (
    ActionPlan,
    BackupEntry,
    BackupManifest,
    BackupVerification,
    ContractIssue,
    OperationName,
    PlanAction,
    PlanTarget,
    ThreadHistoryMode,
    ThreadSnapshot,
    ThreadStatus,
)


def _backup_verification(snapshot: ThreadSnapshot, path: Path) -> BackupVerification:
    path.write_bytes(b"encrypted backup payload")
    manifest = BackupManifest(
        backup_id="backup-id",
        created_at=datetime.now(UTC),
        tool_version="test",
        encryption="age-recipient",
        entries=(
            BackupEntry(
                path=f"logical/threads/{snapshot.id}.json",
                kind="logical",
                size=1,
                sha256="e" * 64,
                thread_id=snapshot.id,
            ),
        ),
        source_fingerprints={snapshot.id: snapshot.backup_fingerprint},
    ).seal()
    ciphertext_sha256, ciphertext_size = hash_file(path)
    return BackupVerification(
        manifest=manifest,
        embedded_source_fingerprints={snapshot.id: snapshot.backup_fingerprint},
        ciphertext_sha256=ciphertext_sha256,
        ciphertext_size=ciphertext_size,
    )


def _record_backup(audit: AuditStore, snapshot: ThreadSnapshot, path: Path) -> BackupManifest:
    verification = _backup_verification(snapshot, path)
    audit.record_verified_backup(verification, path)
    manifest = verification.manifest
    return manifest


def _block_operation(capabilities, operation: OperationName):
    blocked = capabilities.operation(operation).model_copy(
        update={
            "available": False,
            "runtime_contract_fingerprint": None,
            "issues": (
                ContractIssue(
                    code="test_blocked",
                    subject=f"{operation.value} contract is unavailable",
                ),
            ),
        }
    )
    return capabilities.model_copy(
        update={
            "operation_capabilities": tuple(
                blocked if item.operation is operation else item
                for item in capabilities.operation_capabilities
            )
        }
    )


def test_selected_root_contracts_are_task_level(capabilities, snapshot_factory) -> None:
    legacy = snapshot_factory("legacy", history_mode=ThreadHistoryMode.LEGACY)
    paginated = snapshot_factory("paginated", history_mode=ThreadHistoryMode.PAGINATED)
    blocked_pagination = _block_operation(capabilities, OperationName.HISTORY_PAGINATED)

    assert (
        selected_root_block_reason(
            action=PlanAction.ARCHIVE,
            thread_id="legacy",
            snapshots={legacy.id: legacy, paginated.id: paginated},
            capabilities=blocked_pagination,
        )
        is None
    )
    reason = selected_root_block_reason(
        action=PlanAction.ARCHIVE,
        thread_id="paginated",
        snapshots={legacy.id: legacy, paginated.id: paginated},
        capabilities=blocked_pagination,
    )
    assert reason is not None and "history.paginated" in reason


def test_archive_and_unarchive_contracts_are_independent(capabilities, snapshot_factory) -> None:
    archived = snapshot_factory("archived", archived=True)
    snapshots = {archived.id: archived}

    assert (
        selected_root_block_reason(
            action=PlanAction.UNARCHIVE,
            thread_id=archived.id,
            snapshots=snapshots,
            capabilities=_block_operation(capabilities, OperationName.ARCHIVE),
        )
        is None
    )
    reason = selected_root_block_reason(
        action=PlanAction.UNARCHIVE,
        thread_id=archived.id,
        snapshots=snapshots,
        capabilities=_block_operation(capabilities, OperationName.UNARCHIVE),
    )
    assert reason is not None and "unarchive" in reason


def test_archive_planner_keeps_legacy_when_paginated_contract_is_blocked(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    legacy = snapshot_factory(
        "legacy", updated_at=now - timedelta(days=120), history_mode=ThreadHistoryMode.LEGACY
    )
    paginated = snapshot_factory(
        "paginated",
        updated_at=now - timedelta(days=120),
        history_mode=ThreadHistoryMode.PAGINATED,
    )
    snapshots = attach_descendant_closures((legacy, paginated))

    plan = CleanupPlanner().plan_archive(
        snapshots,
        _block_operation(capabilities, OperationName.HISTORY_PAGINATED),
        now=now,
    )

    assert tuple(target.root_thread_id for target in plan.targets) == ("legacy",)


def test_archive_planner_filters_blocked_roots_before_root_ceiling(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    snapshots = attach_descendant_closures(
        tuple(
            snapshot_factory(
                thread_id,
                history_mode=(
                    ThreadHistoryMode.PAGINATED
                    if thread_id.startswith("blocked")
                    else ThreadHistoryMode.LEGACY
                ),
                updated_at=now - timedelta(days=200 - index),
            )
            for index, thread_id in enumerate(
                ("blocked-0", "blocked-1", "eligible-1", "eligible-2")
            )
        )
    )
    capabilities = _block_operation(capabilities, OperationName.HISTORY_PAGINATED)

    plan = CleanupPlanner(CleanupPolicy(maximum_roots=2)).plan_archive(
        snapshots,
        capabilities,
        now=now,
    )

    assert tuple(target.root_thread_id for target in plan.targets) == (
        "eligible-1",
        "eligible-2",
    )


@pytest.mark.parametrize(
    ("action", "archived"),
    ((PlanAction.ARCHIVE, False), (PlanAction.UNARCHIVE, True)),
)
def test_hydration_filters_blocked_roots_before_root_ceiling(
    capabilities, snapshot_factory, action: PlanAction, archived: bool
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    snapshots = attach_descendant_closures(
        tuple(
            snapshot_factory(
                thread_id,
                archived=archived,
                content_complete=False,
                history_mode=(
                    ThreadHistoryMode.PAGINATED
                    if thread_id.startswith("blocked")
                    else ThreadHistoryMode.LEGACY
                ),
                updated_at=now - timedelta(days=200 - index),
            )
            for index, thread_id in enumerate(
                ("blocked-0", "blocked-1", "eligible-1", "eligible-2")
            )
        )
    )
    policy = CleanupPolicy(stale_after=timedelta(days=90), maximum_roots=2)
    planner = CleanupPlanner(policy)
    blocked_capabilities = _block_operation(capabilities, OperationName.HISTORY_PAGINATED)

    hydration_ids = (
        planner.archive_hydration_ids(
            snapshots,
            now=now,
            capabilities=blocked_capabilities,
        )
        if action is PlanAction.ARCHIVE
        else planner.unarchive_hydration_ids(
            snapshots,
            capabilities=blocked_capabilities,
        )
    )

    assert hydration_ids == ("eligible-1", "eligible-2")
    assert len(hydration_ids) <= policy.maximum_roots


def test_archive_plan_requires_complete_old_descendant_closure(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    root = snapshot_factory("root", updated_at=now - timedelta(days=120))
    recent_child = snapshot_factory("child", parent_id="root", updated_at=now - timedelta(days=2))
    snapshots = attach_descendant_closures((root, recent_child))
    plan = CleanupPlanner().plan_archive(snapshots, capabilities, now=now)
    assert plan.targets == ()

    old_child = recent_child.model_copy(update={"updated_at": now - timedelta(days=110)})
    snapshots = attach_descendant_closures((root, old_child))
    plan = CleanupPlanner().plan_archive(snapshots, capabilities, now=now)
    assert len(plan.targets) == 1
    assert set(plan.targets[0].affected_thread_ids) == {"root", "child"}


def test_archive_root_filter_keeps_full_safe_descendant_closure(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    root = snapshot_factory("root", updated_at=now - timedelta(days=120))
    child = snapshot_factory(
        "child", parent_id="root", updated_at=now - timedelta(days=110)
    ).model_copy(update={"cwd": "/different/descendant/project"})
    snapshots = attach_descendant_closures((root, child))
    plan = CleanupPlanner().plan_archive(
        snapshots,
        capabilities,
        now=now,
        criteria=InventoryFilter(cwd="/tmp/project"),
    )
    assert len(plan.targets) == 1
    assert set(plan.targets[0].affected_thread_ids) == {"root", "child"}

    unknown = root.model_copy(update={"status": ThreadStatus.UNKNOWN})
    assert CleanupPlanner().plan_archive((unknown,), capabilities, now=now).targets == ()


def test_explicit_archive_ignores_age_but_keeps_descendant_safety(
    capabilities, snapshot_factory
) -> None:
    root = snapshot_factory("root")
    child = snapshot_factory("child", parent_id="root")
    snapshots = attach_descendant_closures((root, child))

    plan = CleanupPlanner().plan_selected_archive(snapshots, capabilities, ("root",))

    assert plan.action is PlanAction.ARCHIVE
    assert set(plan.targets[0].affected_thread_ids) == {"root", "child"}
    unsafe_child = child.model_copy(update={"status": ThreadStatus.ACTIVE})
    unsafe = attach_descendant_closures((root, unsafe_child))
    with pytest.raises(ValueError, match="active or in an unsafe state"):
        CleanupPlanner().plan_selected_archive(unsafe, capabilities, ("root",))


class _CleanupClient:
    pid = 444

    def __init__(self, *, timeout: bool = False) -> None:
        self.timeout = timeout
        self.calls = 0
        self.archive_calls = 0

    def loaded_thread_ids(self):
        self.calls += 1
        return ()

    def archive_thread(self, thread_id: str) -> None:
        assert thread_id == "root"
        self.calls += 1
        self.archive_calls += 1
        if self.timeout:
            raise RequestTimeout("thread/archive", 1.0)


class _CleanupInventory:
    def __init__(self, before: ThreadSnapshot, after: ThreadSnapshot) -> None:
        self.before = before
        self.after = after
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return (self.before,) if self.calls == 1 else (self.after,)


@pytest.mark.parametrize(
    "confirmation",
    (None, "wrong-plan-id"),
    ids=("missing-confirmation", "wrong-confirmation"),
)
def test_cleanup_apply_requires_exact_confirmation_before_side_effects(
    tmp_path: Path,
    app_paths,
    capabilities,
    snapshot_factory,
    confirmation: str | None,
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    before = snapshot_factory("root", updated_at=now - timedelta(days=120))
    after = before.model_copy(update={"archived": True})
    plan = CleanupPlanner().plan_archive((before,), capabilities, now=now)
    client = _CleanupClient()
    inventory = _CleanupInventory(before, after)

    with AuditStore(app_paths) as audit:
        _record_backup(audit, before, tmp_path / "confirmation.csmbackup")
        with pytest.raises(ValueError, match="cleanup confirmation must equal the exact plan id"):
            CleanupExecutor(
                client=client,  # type: ignore[arg-type]
                inventory=inventory,  # type: ignore[arg-type]
                capabilities=capabilities,
                audit=audit,
            ).apply(plan, confirmation=confirmation)

        assert client.calls == 0
        assert inventory.calls == 0
        assert audit.connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
        assert [event.event_type for event in audit.iter_events(limit=10)] == ["backup.evidence"]


def test_archive_apply_checks_backup_and_never_retries_ambiguous_timeout(
    tmp_path: Path, app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    before = snapshot_factory("root", updated_at=now - timedelta(days=120))
    after = before.model_copy(update={"archived": True})
    plan = CleanupPlanner().plan_archive((before,), capabilities, now=now)
    assert plan.action is PlanAction.ARCHIVE
    client = _CleanupClient(timeout=True)
    inventory = _CleanupInventory(before, after)
    with AuditStore(app_paths) as audit:
        _record_backup(audit, before, tmp_path / "safe.csmbackup")
        completed = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan, confirmation=plan.plan_id)
        audit.verify_chain()
    assert completed == ("root",)
    assert client.archive_calls == 1


@pytest.mark.parametrize("postcondition_satisfied", (True, False))
def test_archive_apply_reconciles_ambiguous_request_error(
    tmp_path: Path,
    app_paths,
    capabilities,
    snapshot_factory,
    postcondition_satisfied: bool,
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    before = snapshot_factory("root", updated_at=now - timedelta(days=120))
    after = before.model_copy(update={"archived": postcondition_satisfied})
    plan = CleanupPlanner().plan_archive((before,), capabilities, now=now)

    class Client(_CleanupClient):
        def archive_thread(self, thread_id: str) -> None:
            super().archive_thread(thread_id)
            raise RequestError(
                "thread/archive",
                {"code": -32603, "message": "response failed after write"},
            )

    client = Client()
    inventory = _CleanupInventory(before, after)
    with AuditStore(app_paths) as audit:
        _record_backup(audit, before, tmp_path / "request-error.csmbackup")
        executor = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        )
        if postcondition_satisfied:
            assert executor.apply(plan, confirmation=plan.plan_id) == ("root",)
            event = next(
                event
                for event in audit.iter_events(limit=10)
                if event.event_type == "archive.apply"
            )
            assert event.details["reconciled_app_server_errors"] == [
                "thread/archive failed (-32603): response failed after write"
            ]
        else:
            with pytest.raises(
                RuntimeError,
                match=r"postcondition unresolved.*response failed after write",
            ):
                executor.apply(plan, confirmation=plan.plan_id)

    assert client.archive_calls == 1


@pytest.mark.parametrize(
    ("child_archived", "expected_calls"),
    ((True, ["root", "child"]), (False, ["root"])),
)
def test_unarchive_applies_only_archived_closure_members(
    app_paths, capabilities, snapshot_factory, child_archived, expected_calls
) -> None:
    root = snapshot_factory("root", archived=True)
    child = snapshot_factory("child", parent_id="root", archived=child_archived)
    snapshots = attach_descendant_closures((root, child))
    plan = CleanupPlanner().plan_unarchive(snapshots, capabilities)

    class Client:
        pid = 444

        def __init__(self) -> None:
            self.archived_ids = {snapshot.id for snapshot in snapshots if snapshot.archived}
            self.calls: list[str] = []

        def loaded_thread_ids(self):
            return ()

        def unarchive_thread(self, thread_id: str) -> None:
            self.calls.append(thread_id)
            self.archived_ids.remove(thread_id)

    client = Client()

    class Inventory:
        def list(self, **_kwargs):
            return tuple(
                snapshot.model_copy(update={"archived": snapshot.id in client.archived_ids})
                for snapshot in snapshots
            )

    with AuditStore(app_paths) as audit:
        completed = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=Inventory(),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan, confirmation=plan.plan_id)

    assert completed == ("root",)
    assert client.calls == expected_calls


def test_audit_verification_detects_event_chain_payload_damage(app_paths) -> None:
    with AuditStore(app_paths) as audit:
        audit.append(event_type="first", actor="test", result="succeeded")
        audit.append(event_type="second", actor="test", result="succeeded")
        with audit.connection:
            audit.connection.execute(
                "UPDATE audit_events SET details_json = ? WHERE sequence = 1",
                ('{"tampered":true}',),
            )
        with pytest.raises(ValueError, match="audit event hash mismatch"):
            audit.verify_chain()


def test_historical_rename_plan_is_rejected_without_a_client_write(
    app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("root")
    plan = ActionPlan.create(
        action=PlanAction.RENAME,
        capability_fingerprint=capabilities.fingerprint,
        targets=(
            PlanTarget(
                root_thread_id=snapshot.id,
                affected_thread_ids=(snapshot.id,),
                snapshot_fingerprints={snapshot.id: snapshot.management_fingerprint},
            ),
        ),
    )
    client = _CleanupClient()

    with AuditStore(app_paths) as audit, pytest.raises(ValueError, match="cannot apply rename"):
        CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=_CleanupInventory(snapshot, snapshot),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan, confirmation=plan.plan_id)

    assert client.archive_calls == 0


def test_archive_apply_rejects_task_history_drift_before_client_write(
    app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    planned = snapshot_factory("root", updated_at=now - timedelta(days=120))
    drifted = planned.model_copy(update={"history_mode": ThreadHistoryMode.PAGINATED})
    plan = CleanupPlanner().plan_archive((planned,), capabilities, now=now)

    with AuditStore(app_paths) as audit, pytest.raises(ValueError, match="snapshot drift"):
        CleanupExecutor(
            client=_CleanupClient(),  # type: ignore[arg-type]
            inventory=_CleanupInventory(drifted, drifted),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan, confirmation=plan.plan_id)


def test_archive_apply_rejects_capability_drift_before_client_write(
    app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    snapshot = snapshot_factory("root", updated_at=now - timedelta(days=120))
    plan = CleanupPlanner().plan_archive((snapshot,), capabilities, now=now)
    drifted_capabilities = capabilities.model_copy(update={"initialize_fingerprint": "changed"})
    client = _CleanupClient()

    with AuditStore(app_paths) as audit, pytest.raises(ValueError, match="capability drift"):
        CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=_CleanupInventory(snapshot, snapshot),  # type: ignore[arg-type]
            capabilities=drifted_capabilities,
            audit=audit,
        ).apply(plan, confirmation=plan.plan_id)

    assert client.archive_calls == 0


def test_replaced_backup_invalidates_cleanup_gate(
    tmp_path: Path, app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    snapshot = snapshot_factory("root", updated_at=now - timedelta(days=120))
    plan = CleanupPlanner().plan_archive((snapshot,), capabilities, now=now)
    path = tmp_path / "replace.csmbackup"
    with AuditStore(app_paths) as audit:
        _record_backup(audit, snapshot, path)
        evidence = audit.verified_backup("root", snapshot.backup_fingerprint)
        assert evidence is not None and evidence.is_current()
        path.write_bytes(b"different ciphertext")
        assert not evidence.is_current()
        executor = CleanupExecutor(
            client=_CleanupClient(),  # type: ignore[arg-type]
            inventory=_CleanupInventory(snapshot, snapshot.model_copy(update={"archived": True})),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        )
        with pytest.raises(ValueError, match="verified encrypted backup"):
            executor.apply(plan, confirmation=plan.plan_id)


def test_audit_refuses_ciphertext_replaced_after_full_verification(
    tmp_path: Path, app_paths, snapshot_factory
) -> None:
    snapshot = snapshot_factory("root")
    path = tmp_path / "replace-before-audit.csmbackup"
    verification = _backup_verification(snapshot, path)
    path.write_bytes(b"replacement ciphertext")

    with (
        AuditStore(app_paths) as audit,
        pytest.raises(ValueError, match="changed before audit recording"),
    ):
        audit.record_verified_backup(verification, path)

    with AuditStore(app_paths) as audit:
        assert audit.verified_backup(snapshot.id, snapshot.backup_fingerprint) is None


def test_archive_plan_and_apply_reject_ephemeral_or_archive_state_drift(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    ephemeral = snapshot_factory("ephemeral", ephemeral=True, updated_at=now - timedelta(days=120))
    assert CleanupPlanner().plan_archive((ephemeral,), capabilities, now=now).targets == ()

    source = snapshot_factory("root", updated_at=now - timedelta(days=120))
    plan = CleanupPlanner().plan_archive((source,), capabilities, now=now)
    with pytest.raises(ValueError, match=r"snapshot drift|already archived"):
        CleanupExecutor._verify_snapshot_drift(
            plan, (source.model_copy(update={"archived": True}),)
        )


def test_archive_plan_rejects_overlapping_dual_parent_cascades(
    capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    root = snapshot_factory("root", updated_at=now - timedelta(days=120))
    other = snapshot_factory("other", updated_at=now - timedelta(days=120))
    dual = snapshot_factory(
        "dual", parent_id="other", updated_at=now - timedelta(days=120)
    ).model_copy(update={"forked_from_id": "root"})
    snapshots = attach_descendant_closures((root, other, dual))

    plan = CleanupPlanner().plan_archive(snapshots, capabilities, now=now)

    assert plan.targets == ()
