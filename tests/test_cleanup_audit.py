from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_session_manager.app_server import RequestError, RequestTimeout
from codex_session_manager.audit import AuditStore
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner, ProcessGuard
from codex_session_manager.hashing import hash_file
from codex_session_manager.inventory import InventoryFilter, attach_descendant_closures
from codex_session_manager.models import (
    ActionPlan,
    BackupEntry,
    BackupManifest,
    BackupVerification,
    PlanAction,
    PlanTarget,
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
        self.archive_calls = 0

    def loaded_thread_ids(self):
        return ()

    def archive_thread(self, thread_id: str) -> None:
        assert thread_id == "root"
        self.archive_calls += 1
        if self.timeout:
            raise RequestTimeout("thread/archive", 1.0)


class _RenameClient:
    pid = 445

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def loaded_thread_ids(self):
        return ()

    def rename_thread(self, thread_id: str, name: str) -> None:
        self.calls.append((thread_id, name))


class _CleanupInventory:
    def __init__(self, before: ThreadSnapshot, after: ThreadSnapshot) -> None:
        self.before = before
        self.after = after
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return (self.before,) if self.calls == 1 else (self.after,)


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
        manifest = _record_backup(audit, before, tmp_path / "safe.csmbackup")
        completed = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan)
        trusted = audit.trusted_archive("root")
        assert trusted is not None
        assert trusted.manifest_sha256 == manifest.manifest_sha256
        audit.invalidate_trusted_archive(thread_id="root", plan_sha256="u" * 64)
        assert audit.trusted_archive("root") is None
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
            assert executor.apply(plan) == ("root",)
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
                executor.apply(plan)

    assert client.archive_calls == 1


def test_purge_apply_is_closed_before_inventory_or_app_server(
    app_paths,
    capabilities,
) -> None:
    plan = ActionPlan.create(
        action=PlanAction.PURGE,
        capability_fingerprint=capabilities.fingerprint,
        targets=(
            PlanTarget(
                root_thread_id="root",
                affected_thread_ids=("root",),
                snapshot_fingerprints={"root": "f" * 64},
            ),
        ),
        options={"manual_only": True, "trusted_archive_required": True},
    )

    class UnexpectedCall:
        def __getattr__(self, name: str):
            raise AssertionError(f"unexpected call while purge is blocked: {name}")

    with (
        AuditStore(app_paths) as audit,
        pytest.raises(RuntimeError, match="CLOSED_WITH_UPSTREAM_BLOCKER"),
    ):
        CleanupExecutor(
            client=UnexpectedCall(),  # type: ignore[arg-type]
            inventory=UnexpectedCall(),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan, confirmation="确认删除")


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
        ).apply(plan)

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


def test_rename_uses_sealed_plan_and_verifies_title_postcondition(
    app_paths, capabilities, snapshot_factory
) -> None:
    before = snapshot_factory("root")
    after = before.model_copy(update={"title": "新的对话名称"})
    plan = CleanupPlanner().plan_rename(
        (before,), capabilities, thread_id="root", new_name=" 新的对话名称 "
    )
    client = _RenameClient()
    inventory = _CleanupInventory(before, after)

    with AuditStore(app_paths) as audit:
        completed = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(plan)

    assert plan.action is PlanAction.RENAME
    assert completed == ("root",)
    assert client.calls == [("root", "新的对话名称")]


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
            executor.apply(plan)


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


def test_purge_plan_rejects_ephemeral_and_accepts_new_trusted_archive(
    tmp_path: Path, app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    ephemeral = snapshot_factory(
        "ephemeral",
        archived=True,
        ephemeral=True,
        updated_at=now - timedelta(days=200),
    )
    normal = snapshot_factory("normal", archived=True, updated_at=now - timedelta(days=200))
    with AuditStore(app_paths) as audit:
        manifest = _record_backup(audit, normal, tmp_path / "normal.csmbackup")
        audit.record_trusted_archive(
            thread_id="normal",
            plan_sha256="p" * 64,
            manifest_sha256=manifest.manifest_sha256,
            archived_at=now,
        )
        planner = CleanupPlanner()
        candidates = planner.purge_candidates((ephemeral, normal), audit, now=now)
        plan = planner.plan_purge((ephemeral, normal), capabilities, audit, now=now)
    assert [snapshot.id for snapshot in candidates] == ["normal"]
    assert [target.root_thread_id for target in plan.targets] == ["normal"]
    assert plan.options["trusted_archive_required"] is True
    assert "minimum_archive_days" not in plan.options
    with pytest.raises(ValueError, match=r"snapshot drift|no longer archived"):
        CleanupExecutor._verify_snapshot_drift(
            plan, (normal.model_copy(update={"archived": False}),)
        )


def test_explicit_purge_plans_only_selected_eligible_roots(
    tmp_path: Path, app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first = snapshot_factory("first", archived=True, updated_at=now - timedelta(days=200))
    second = snapshot_factory("second", archived=True, updated_at=now - timedelta(days=200))
    with AuditStore(app_paths) as audit:
        first_manifest = _record_backup(audit, first, tmp_path / "first.csmbackup")
        second_manifest = _record_backup(audit, second, tmp_path / "second.csmbackup")
        audit.record_trusted_archive(
            thread_id="first",
            plan_sha256="1" * 64,
            manifest_sha256=first_manifest.manifest_sha256,
            archived_at=now,
        )
        audit.record_trusted_archive(
            thread_id="second",
            plan_sha256="2" * 64,
            manifest_sha256=second_manifest.manifest_sha256,
            archived_at=now,
        )

        plan = CleanupPlanner().plan_selected_purge(
            (first, second), capabilities, audit, ("second",), now=now
        )
        assert plan.options == {
            "manual_only": True,
            "manual_selection": True,
            "trusted_archive_required": True,
        }

        with pytest.raises(ValueError, match="exactly one root"):
            CleanupPlanner().plan_selected_purge(
                (first, second), capabilities, audit, ("first", "second"), now=now
            )

        first_plan = CleanupPlanner().plan_selected_purge(
            (first, second), capabilities, audit, ("first",), now=now
        )
        multi_root_plan = ActionPlan.create(
            action=PlanAction.PURGE,
            capability_fingerprint=capabilities.fingerprint,
            targets=(*first_plan.targets, *plan.targets),
        )
        with pytest.raises(ValueError, match="exactly one root"):
            CleanupExecutor(
                client=_CleanupClient(),  # type: ignore[arg-type]
                inventory=_CleanupInventory(first, first),  # type: ignore[arg-type]
                capabilities=capabilities,
                audit=audit,
            ).apply(
                multi_root_plan,
                confirmation="确认删除",
            )

        plan_without_trusted_gate = ActionPlan.create(
            action=PlanAction.PURGE,
            capability_fingerprint=capabilities.fingerprint,
            targets=plan.targets,
            options={"manual_only": True},
        )
        executor = CleanupExecutor(
            client=_CleanupClient(),  # type: ignore[arg-type]
            inventory=_CleanupInventory(second, second),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        )
        with pytest.raises(ValueError, match="manual trusted-archive gate"):
            executor._verify_purge_gate(
                plan_without_trusted_gate,
                plan_without_trusted_gate.targets,
                {second.id: second},
            )

    assert [target.root_thread_id for target in plan.targets] == ["second"]


def test_purge_requires_archive_bound_manifest_and_intact_audit_chain(
    tmp_path: Path, app_paths, capabilities, snapshot_factory
) -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    snapshot = snapshot_factory("root", archived=True, updated_at=now - timedelta(days=200))
    with AuditStore(app_paths) as audit:
        _record_backup(audit, snapshot, tmp_path / "root.csmbackup")
        audit.record_trusted_archive(
            thread_id="root",
            plan_sha256="p" * 64,
            manifest_sha256="wrong-manifest",
            archived_at=now - timedelta(days=15),
        )
        assert CleanupPlanner().plan_purge((snapshot,), capabilities, audit, now=now).targets == ()

        audit.connection.execute(
            "UPDATE trusted_archives SET manifest_sha256 = ? WHERE thread_id = ?",
            ("tampered", "root"),
        )
        audit.connection.commit()
        with pytest.raises(ValueError, match="not bound to its audit event"):
            audit.trusted_archive("root")


def test_archived_not_loaded_purge_accepts_terminal_thread_not_found(
    tmp_path: Path,
    app_paths,
    capabilities,
    snapshot_factory,
    monkeypatch,
) -> None:
    snapshot = snapshot_factory(
        "root",
        archived=True,
        status=ThreadStatus.NOT_LOADED,
    )

    class Client:
        pid = 444

        def __init__(self) -> None:
            self.deleted = False
            self.background_terminal_checks = 0

        def loaded_thread_ids(self):
            return ()

        def background_terminals(self, thread_id: str):
            self.background_terminal_checks += 1
            raise RequestError(
                "thread/backgroundTerminals/list",
                {"code": -32600, "message": f"thread not found: {thread_id}"},
            )

        def delete_thread(self, thread_id: str) -> None:
            assert thread_id == snapshot.id
            self.deleted = True

    client = Client()

    class Inventory:
        def __init__(self) -> None:
            self.target_reads = 0

        def list_for_targets(self, target_ids, **_kwargs):
            assert target_ids == (snapshot.id,)
            self.target_reads += 1
            return () if client.deleted else (snapshot,)

        def list(self, **_kwargs):
            assert not _kwargs.get("include_turns")
            return () if client.deleted else (snapshot,)

    inventory = Inventory()

    with AuditStore(app_paths) as audit:
        manifest = _record_backup(audit, snapshot, tmp_path / "root.csmbackup")
        audit.record_trusted_archive(
            thread_id=snapshot.id,
            plan_sha256="p" * 64,
            manifest_sha256=manifest.manifest_sha256,
        )
        plan = CleanupPlanner().plan_selected_purge(
            (snapshot,), capabilities, audit, (snapshot.id,)
        )
        monkeypatch.setattr(
            "codex_session_manager.cleanup.ProcessGuard.assert_no_other_codex_processes",
            lambda *, controlled_pid: None,
        )
        monkeypatch.setattr("codex_session_manager.cleanup.PURGE_EXECUTION_ENABLED", True)

        completed = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(
            plan,
            confirmation="确认删除",
        )

    assert completed == (snapshot.id,)
    assert client.deleted
    assert client.background_terminal_checks == 2
    assert inventory.target_reads == 2


def test_process_guard_ignores_controlled_app_server_descendant_but_blocks_other_codex(
    monkeypatch,
) -> None:
    output = "\n".join(
        (
            "100 1 /usr/local/bin/node codex.js app-server --listen stdio://",
            "101 100 /vendor/bin/codex app-server --listen stdio://",
            "200 1 /usr/local/bin/codex app-server --listen stdio://",
        )
    )
    monkeypatch.setattr(
        "codex_session_manager.cleanup.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output, stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="200") as error:
        ProcessGuard.assert_no_other_codex_processes(controlled_pid=100)

    assert "101 " not in str(error.value)


@pytest.mark.parametrize(
    ("status", "error"),
    (
        (
            ThreadStatus.IDLE,
            {"code": -32600, "message": "thread not found: root"},
        ),
        (
            ThreadStatus.NOT_LOADED,
            {"code": -32600, "message": "thread not found: another-root"},
        ),
        (
            ThreadStatus.NOT_LOADED,
            {"code": -32601, "message": "thread not found: root"},
        ),
    ),
)
def test_purge_does_not_hide_other_terminal_query_failures(
    app_paths, capabilities, snapshot_factory, status, error
) -> None:
    snapshot = snapshot_factory("root", archived=True, status=status)

    class Client:
        def background_terminals(self, _thread_id: str):
            raise RequestError("thread/backgroundTerminals/list", error)

    with AuditStore(app_paths) as audit:
        executor = CleanupExecutor(
            client=Client(),  # type: ignore[arg-type]
            inventory=object(),  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        )
        with pytest.raises(RequestError):
            executor._purge_background_terminals(snapshot)


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
