from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import IO

import pytest

from codex_session_manager.audit import AuditStore
from codex_session_manager.backup import DecryptionSpec, EncryptionSpec
from codex_session_manager.cleanup import CleanupPolicy
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import PlanAction
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
from codex_session_manager.sensitive import SensitiveScanResult
from codex_session_manager.workflows import ApplicationWorkflows


class _PlainSession:
    def __init__(self, destination: Path) -> None:
        self.stream: IO[bytes] = destination.open("wb")

    def finish(self) -> None:
        self.stream.close()

    def abort(self) -> None:
        self.stream.close()


class _PlainCipher:
    """Test transport; production workflows still default to age."""

    def open_encrypt(self, destination: Path, _spec: EncryptionSpec) -> _PlainSession:
        return _PlainSession(destination)

    @contextlib.contextmanager
    def open_decrypt(self, source: Path, _spec: DecryptionSpec) -> Iterator[IO[bytes]]:
        with source.open("rb") as stream:
            yield stream


class _WorkflowClient:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.closed = False

    def list_threads(self, *, archived: bool = False):
        if archived:
            return iter(())
        return iter(
            (
                {
                    "id": "root",
                    "name": "Root",
                    "updatedAt": "2025-01-01T00:00:00Z",
                    "status": {"type": "idle"},
                },
                {
                    "id": "child",
                    "name": "Child",
                    "parentThreadId": "root",
                    "updatedAt": "2025-01-02T00:00:00Z",
                    "status": {"type": "idle"},
                },
                {
                    "id": "recent",
                    "name": "Recent",
                    "updatedAt": "2099-01-01T00:00:00Z",
                    "status": {"type": "idle"},
                },
            )
        )

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        self.reads.append(thread_id)
        parent = "root" if thread_id == "child" else None
        return {
            "id": thread_id,
            "name": thread_id.title(),
            "parentThreadId": parent,
            "updatedAt": "2025-01-01T00:00:00Z",
            "status": {"type": "idle"},
            "turns": [{"id": f"{thread_id}-turn", "status": "completed", "items": []}],
        }

    def close(self) -> None:
        self.closed = True


class _ArchivingWorkflowClient(_WorkflowClient):
    def __init__(self) -> None:
        super().__init__()
        self.archived_ids: set[str] = set()
        self.archive_calls: list[str] = []

    def list_threads(self, *, archived: bool = False):
        values = (
            {
                "id": "root",
                "name": "Root",
                "updatedAt": "2025-01-01T00:00:00Z",
                "status": {"type": "idle"},
            },
            {
                "id": "child",
                "name": "Child",
                "parentThreadId": "root",
                "updatedAt": "2025-01-02T00:00:00Z",
                "status": {"type": "idle"},
            },
        )
        return iter(
            value for value in values if (str(value["id"]) in self.archived_ids) is archived
        )

    def archive_thread(self, thread_id: str) -> None:
        self.archive_calls.append(thread_id)
        if thread_id == "root":
            self.archived_ids.update(("root", "child"))
        else:
            self.archived_ids.add(thread_id)

    def loaded_thread_ids(self) -> tuple[str, ...]:
        return ()


class _DriftingWorkflowClient(_ArchivingWorkflowClient):
    def __init__(self) -> None:
        super().__init__()
        self.root_reads = 0

    def read_thread(self, thread_id: str, *, include_turns: bool = False):
        value = super().read_thread(thread_id, include_turns=include_turns)
        if thread_id == "root":
            self.root_reads += 1
            if self.root_reads >= 4:
                value["name"] = "Root changed after backup"
        return value


def test_selected_archive_workflow_hydrates_only_target_closure(app_paths, capabilities) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    workflows = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
    )
    prepared = workflows.prepare_selected_archive(("root",))

    assert client.reads == ["child", "root"]
    assert client.closed
    assert prepared.path.is_file()
    assert prepared.plan.action is PlanAction.ARCHIVE
    assert prepared.plan.targets[0].affected_thread_ids == ("root", "child")


def test_policy_archive_workflow_prefilters_summaries_before_hydration(
    app_paths, capabilities
) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    prepared = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
    ).prepare_cleanup_plan(
        action=PlanAction.ARCHIVE,
        policy=CleanupPolicy(stale_after=timedelta(days=90)),
    )

    assert client.reads == ["child", "root"]
    assert {target.root_thread_id for target in prepared.plan.targets} == {"root"}


def test_cleanup_inspection_offers_current_safe_supplemental_root(app_paths, capabilities) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    result = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
    ).inspect_cleanup_candidates(("root",))

    assert result.supplemental_root_ids == ("recent",)
    assert result.purge_root_ids == ()
    hydrated = {snapshot.id for snapshot in result.snapshots if snapshot.content_complete}
    assert hydrated == {"root", "child", "recent"}


def test_workflow_closes_connection_when_target_is_stale(app_paths, capabilities) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    workflows = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="missing"):
        workflows.prepare_selected_archive(("missing",))
    assert client.closed
    assert client.reads == []


def test_backup_workflow_expands_closure_verifies_and_records_audit(
    tmp_path, app_paths, capabilities
) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    destination = tmp_path / "workflow.csmbackup"
    result = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
        backup_backend_factory=_PlainCipher,
    ).create_backup(
        destination,
        thread_ids=("root",),
        encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
        verification_decryption=DecryptionSpec(),
        include_raw=False,
    )

    assert result.covered_thread_ids == ("child", "root")
    assert set(result.manifest.source_fingerprints) == {"child", "root"}
    assert client.reads == ["child", "root", "child", "root"]
    assert client.closed
    with AuditStore(app_paths) as audit:
        audit.verify_chain()
        for thread_id, source_fingerprint in result.manifest.source_fingerprints.items():
            assert audit.verified_backup(thread_id, source_fingerprint) is not None


def test_backup_and_archive_rebuilds_review_plan_and_links_audit(
    tmp_path, app_paths, capabilities
) -> None:
    client = _ArchivingWorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    current = InventoryService(client).list_for_targets(("root",))
    root = next(snapshot for snapshot in current if snapshot.id == "root")
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=root.id,
                source_fingerprint=root.management_fingerprint,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="LLM 初筛后由用户最终保留",
                confidence=0.91,
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
    client.reads.clear()
    destination = tmp_path / "cleanup-archive.csmbackup"
    workflows = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
        backup_backend_factory=_PlainCipher,
    )

    result = workflows.backup_and_archive(
        destination,
        selected_ids=(root.id,),
        encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
        verification_decryption=DecryptionSpec(),
        review_request=request,
        include_raw=False,
    )

    assert destination.is_file()
    assert result.backup.covered_thread_ids == ("child", "root")
    assert result.action.completed_ids == ("root",)
    assert client.archive_calls == ["root"]
    assert client.archived_ids == {"root", "child"}
    inspected = workflows.inspect_cleanup_candidates(("root",))
    assert inspected.verified_backup_ids == frozenset({"root", "child"})
    with AuditStore(app_paths) as audit:
        audit.verify_chain()
        linked = [
            event
            for event in audit.iter_events(limit=100)
            if event.event_type == "cleanup.backup-and-archive"
        ]
    assert len(linked) == 1
    assert linked[0].result == "succeeded"
    assert linked[0].plan_sha256 == result.action.plan.plan_sha256
    assert linked[0].details["manifest_sha256"] == result.backup.manifest.manifest_sha256


def test_backup_and_archive_stops_when_review_fingerprint_drifts_after_backup(
    tmp_path, app_paths, capabilities
) -> None:
    client = _DriftingWorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    current = InventoryService(client).list_for_targets(("root",))
    root = next(snapshot for snapshot in current if snapshot.id == "root")
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id=root.id,
                source_fingerprint=root.management_fingerprint,
                suggested_action=SuggestedAction.ARCHIVE,
                reason="LLM 初筛",
                confidence=0.9,
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
    destination = tmp_path / "drifted-cleanup.csmbackup"
    workflows = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
        backup_backend_factory=_PlainCipher,
    )

    with pytest.raises(ValueError, match="stale"):
        workflows.backup_and_archive(
            destination,
            selected_ids=(root.id,),
            encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
            verification_decryption=DecryptionSpec(),
            review_request=request,
            include_raw=False,
        )

    assert destination.is_file()
    assert client.archive_calls == []
    with AuditStore(app_paths) as audit:
        audit.verify_chain()
        linked = [
            event
            for event in audit.iter_events(limit=100)
            if event.event_type == "cleanup.backup-and-archive"
        ]
    assert len(linked) == 1
    assert linked[0].result == "failed"


def test_sensitive_scan_pipelines_local_scanning_across_worker_threads(
    app_paths, capabilities, monkeypatch
) -> None:
    client = _WorkflowClient()

    def connect(**_kwargs):
        return client, capabilities

    rendezvous = threading.Barrier(2)
    worker_names: set[str] = set()

    def concurrent_scan(_snapshot, *, cancelled=None):
        assert cancelled is not None
        assert not cancelled()
        worker_names.add(threading.current_thread().name)
        rendezvous.wait(timeout=0.25)
        return SensitiveScanResult()

    monkeypatch.setattr(
        "codex_session_manager.workflows.scan_sensitive_snapshot",
        concurrent_scan,
    )
    progress: list[tuple[int, int]] = []

    result = ApplicationWorkflows(
        paths=app_paths,
        connection_factory=connect,  # type: ignore[arg-type]
    ).scan_sensitive_threads(
        ("one", "two", "three", "four"),
        cancelled=lambda: False,
        progress=progress.append,
    )

    assert result.scanned == 4
    assert result.failed == 0
    assert not result.cancelled
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert len(worker_names) >= 2
    assert client.closed
