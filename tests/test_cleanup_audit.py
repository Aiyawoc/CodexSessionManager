from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_session_manager.app_server import RequestTimeout
from codex_session_manager.audit import AuditStore
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner
from codex_session_manager.inventory import InventoryFilter, attach_descendant_closures
from codex_session_manager.models import (
    BackupEntry,
    BackupManifest,
    BackupVerification,
    PlanAction,
    ThreadSnapshot,
    ThreadStatus,
)


def _record_backup(audit: AuditStore, snapshot: ThreadSnapshot, path: Path) -> BackupManifest:
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
    audit.record_verified_backup(
        BackupVerification(
            manifest=manifest,
            embedded_source_fingerprints={snapshot.id: snapshot.backup_fingerprint},
        ),
        path,
    )
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


def test_purge_plan_rejects_ephemeral_and_untrusted_archive(
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
            archived_at=now - timedelta(days=15),
        )
        plan = CleanupPlanner().plan_purge((ephemeral, normal), capabilities, audit, now=now)
    assert [target.root_thread_id for target in plan.targets] == ["normal"]
    with pytest.raises(ValueError, match=r"snapshot drift|no longer archived"):
        CleanupExecutor._verify_snapshot_drift(
            plan, (normal.model_copy(update={"archived": False}),)
        )


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
