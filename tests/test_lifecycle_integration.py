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
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner
from codex_session_manager.inventory import normalize_thread

PROJECT_ROOT = Path(__file__).parents[1]


class _LifecycleClient:
    pid = 321

    def __init__(self, raw_thread: dict[str, object]) -> None:
        self.raw_thread = raw_thread
        self.archived = False

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        assert thread_id == "thread-1"
        assert include_turns
        return self.raw_thread

    def loaded_thread_ids(self):
        return ()

    def archive_thread(self, thread_id: str) -> None:
        assert thread_id == "thread-1"
        self.archived = True

    def unarchive_thread(self, thread_id: str) -> None:
        assert thread_id == "thread-1"
        self.archived = False


class _LifecycleInventory:
    def __init__(self, client: _LifecycleClient, snapshot) -> None:
        self.client = client
        self.snapshot = snapshot

    def list(self, **_kwargs):
        return (self.snapshot.model_copy(update={"archived": self.client.archived}),)

    def list_for_targets(self, _target_ids, **kwargs):
        return self.list(**kwargs)


def _age_executable() -> Path | None:
    override = os.environ.get("CSM_TEST_AGE_BIN")
    if override:
        return Path(override)
    candidate = PROJECT_ROOT / "vendor" / "age" / "age"
    return candidate if candidate.is_file() else None


@pytest.mark.integration
def test_real_age_backup_archive_and_unarchive_lifecycle(
    tmp_path: Path, app_paths, capabilities
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
        ).apply(archive_plan, confirmation=archive_plan.plan_id)
        assert archived == ("thread-1",)
        assert client.archived

        archived_snapshot = snapshot.model_copy(update={"archived": True})
        unarchive_plan = CleanupPlanner().plan_unarchive((archived_snapshot,), capabilities)
        unarchived = CleanupExecutor(
            client=client,  # type: ignore[arg-type]
            inventory=inventory,  # type: ignore[arg-type]
            capabilities=capabilities,
            audit=audit,
        ).apply(
            unarchive_plan,
            confirmation=unarchive_plan.plan_id,
        )
        assert unarchived == ("thread-1",)
        assert not client.archived
        audit.verify_chain()
        event_types = {event.event_type for event in audit.iter_events(limit=100)}
        assert {
            "backup.evidence",
            "backup.verify",
            "archive.apply",
            "unarchive.apply",
        }.issubset(event_types)

        private_key = identity.read_bytes()
        persisted_paths = tuple(app_paths.audit_db.parent.glob(f"{app_paths.audit_db.name}*"))
        persisted_paths += tuple(app_paths.log_dir.glob("*"))
        assert all(
            private_key not in path.read_bytes() for path in persisted_paths if path.is_file()
        )
