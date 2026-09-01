from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_session_manager.audit import AuditStore
from codex_session_manager.backup import (
    AgeBackend,
    BackupService,
    DecryptionSpec,
    EncryptionSpec,
)
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner, ProcessGuard
from codex_session_manager.inventory import normalize_thread

PROJECT_ROOT = Path(__file__).parents[1]


class _LifecycleClient:
    pid = 321

    def __init__(self, raw_thread: dict[str, object]) -> None:
        self.raw_thread = raw_thread
        self.archived = False
        self.deleted = False

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        assert thread_id == "thread-1"
        assert include_turns
        return self.raw_thread

    def loaded_thread_ids(self):
        return ()

    def background_terminals(self, thread_id: str):
        assert thread_id == "thread-1"
        return ()

    def archive_thread(self, thread_id: str) -> None:
        assert thread_id == "thread-1"
        self.archived = True

    def delete_thread(self, thread_id: str) -> None:
        assert thread_id == "thread-1"
        self.deleted = True


class _LifecycleInventory:
    def __init__(self, client: _LifecycleClient, snapshot) -> None:
        self.client = client
        self.snapshot = snapshot

    def list(self, **_kwargs):
        if self.client.deleted:
            return ()
        return (self.snapshot.model_copy(update={"archived": self.client.archived}),)


def _age_executable() -> Path | None:
    override = os.environ.get("CSM_TEST_AGE_BIN")
    if override:
        return Path(override)
    candidate = PROJECT_ROOT / "vendor" / "age" / "age"
    return candidate if candidate.is_file() else None


@pytest.mark.integration
def test_real_age_backup_archive_and_purge_lifecycle(
    tmp_path: Path, app_paths, capabilities, monkeypatch
) -> None:
    age_executable = _age_executable()
    ssh_keygen = shutil.which("ssh-keygen")
    if age_executable is None or not os.access(age_executable, os.X_OK):
        pytest.skip("project or bundle age executable is unavailable")
    if ssh_keygen is None:
        pytest.skip("ssh-keygen is unavailable for an ephemeral age recipient")

    identity = tmp_path / "age-test-identity"
    subprocess.run(
        [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(identity)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    recipient = identity.with_suffix(".pub").read_text(encoding="utf-8").strip()
    raw_thread: dict[str, object] = {
        "id": "thread-1",
        "name": "Lifecycle fixture",
        "cwd": "/tmp/project",
        "status": {"type": "idle"},
        "turns": [
            {
                "id": "turn-1",
                "status": "completed",
                "items": [
                    {
                        "id": "message-1",
                        "type": "agentMessage",
                        "role": "assistant",
                        "text": "encrypted lifecycle content",
                    }
                ],
            }
        ],
    }
    now = datetime(2026, 8, 12, tzinfo=UTC)
    snapshot = normalize_thread(raw_thread, content_complete=True).model_copy(
        update={"updated_at": now - timedelta(days=120)}
    )
    client = _LifecycleClient(raw_thread)
    inventory = _LifecycleInventory(client, snapshot)
    destination = tmp_path / "lifecycle.csmbackup"
    backend = AgeBackend(age_executable)

    with AuditStore(app_paths) as audit:
        manifest = BackupService(
            client=client,  # type: ignore[arg-type]
            paths=app_paths,
            backend=backend,
            audit=audit,
        ).create(
            destination,
            snapshots=(snapshot,),
            encryption=EncryptionSpec(mode="age-recipient", recipient=recipient),
            verification_decryption=DecryptionSpec(identity_file=identity),
            include_raw=False,
        )
        assert destination.read_bytes().startswith(b"age-encryption.org/v1")
        assert manifest.encryption == "age-recipient"
        assert manifest.source_fingerprints == {
            "thread-1": snapshot.backup_fingerprint,
        }
        if os.name != "nt":
            assert destination.stat().st_mode & 0o777 == 0o600
        assert not tuple(tmp_path.glob(".lifecycle.csmbackup.*.encrypted.tmp"))
        evidence = audit.verified_backup("thread-1", snapshot.backup_fingerprint)
        assert evidence is not None
        assert evidence.manifest_sha256 == manifest.manifest_sha256
        assert evidence.is_current()

        archive_plan = CleanupPlanner().plan_archive((snapshot,), capabilities, now=now)
        archived = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(archive_plan)
        assert archived == ("thread-1",)
        assert client.archived

        trusted = audit.trusted_archive("thread-1")
        assert trusted is not None
        assert trusted.plan_sha256 == archive_plan.plan_sha256
        assert trusted.manifest_sha256 == manifest.manifest_sha256
        archived_snapshot = snapshot.model_copy(update={"archived": True})
        purge_plan = CleanupPlanner().plan_purge((archived_snapshot,), capabilities, audit, now=now)
        assert tuple(target.root_thread_id for target in purge_plan.targets) == ("thread-1",)
        monkeypatch.setattr(
            ProcessGuard,
            "assert_no_other_codex_processes",
            staticmethod(lambda *, controlled_pid: None),
        )
        purged = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(
            purge_plan,
            confirmation=purge_plan.plan_id,
            permanent_phrase="PERMANENTLY DELETE CODEX TASKS",
        )
        assert purged == ("thread-1",)
        assert client.deleted
        audit.verify_chain()
        event_types = {event.event_type for event in audit.iter_events(limit=100)}
        assert {
            "backup.evidence",
            "backup.verify",
            "archive.apply",
            "archive.evidence",
            "purge.apply",
        }.issubset(event_types)

        private_key = identity.read_bytes()
        persisted_paths = tuple(app_paths.audit_db.parent.glob(f"{app_paths.audit_db.name}*"))
        persisted_paths += tuple(app_paths.log_dir.glob("*"))
        assert all(
            private_key not in path.read_bytes() for path in persisted_paths if path.is_file()
        )
