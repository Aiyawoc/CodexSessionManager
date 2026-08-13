"""Application workflow Module shared by CLI, GUI, Skill, and Hook adapters.

This is the connection and orchestration Seam.  Domain planners/executors keep
their safety logic; adapters no longer duplicate App Server lifecycle, targeted
inventory hydration, plan persistence, audit ownership, and result packaging.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

from codex_session_manager.app_server import SubprocessAppServer, connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.backup import (
    AgeBackend,
    BackupService,
    CipherBackend,
    DecryptionSpec,
    EncryptionSpec,
)
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner, CleanupPolicy
from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.inventory import (
    InventoryFilter,
    InventoryService,
    target_closure_ids,
)
from codex_session_manager.models import (
    ActionPlan,
    BackupManifest,
    CapabilityMatrix,
    PlanAction,
    ThreadSnapshot,
    TrimPlan,
)
from codex_session_manager.plans import PlanModel, PlanStore
from codex_session_manager.sensitive import (
    SensitiveScanCancelled,
    SensitiveScanResult,
    scan_sensitive_snapshot,
)
from codex_session_manager.trim import TrimExecutor


class ConnectionFactory(Protocol):
    def __call__(
        self,
        *,
        executable: str | None = None,
        request_timeout: float = 30.0,
        experimental_api: bool = False,
    ) -> tuple[SubprocessAppServer, CapabilityMatrix]: ...


@dataclass(frozen=True, slots=True)
class InventoryResult:
    capabilities: CapabilityMatrix
    snapshots: tuple[ThreadSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ThreadReadResult:
    capabilities: CapabilityMatrix
    snapshot: ThreadSnapshot


@dataclass(frozen=True, slots=True)
class PreparedAction:
    plan: ActionPlan
    path: Path


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    plan: ActionPlan
    completed_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupCreationResult:
    manifest: BackupManifest
    covered_thread_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SensitiveScanBatch:
    matches: dict[str, SensitiveScanResult]
    scanned: int
    failed: int
    cancelled: bool = False


_SENSITIVE_SCAN_MAX_WORKERS = 4


class WorkflowSession:
    """One initialized App Server connection with shared application services."""

    def __init__(
        self,
        *,
        paths: AppPaths,
        connection_factory: ConnectionFactory,
        request_timeout: float,
        experimental_api: bool,
    ) -> None:
        self.paths = paths
        self.connection_factory = connection_factory
        self.request_timeout = request_timeout
        self.experimental_api = experimental_api
        self.client: SubprocessAppServer | None = None
        self.capabilities: CapabilityMatrix | None = None
        self.inventory: InventoryService | None = None
        self._plans: PlanStore | None = None
        self._audit: AuditStore | None = None

    @property
    def plans(self) -> PlanStore:
        if self._plans is None:
            self._plans = PlanStore(self.paths)
        return self._plans

    @property
    def audit(self) -> AuditStore:
        if self._audit is None:
            self._audit = AuditStore(self.paths)
        return self._audit

    def __enter__(self) -> Self:
        client, capabilities = self.connection_factory(
            request_timeout=self.request_timeout,
            experimental_api=self.experimental_api,
        )
        self.client = client
        self.capabilities = capabilities
        self.inventory = InventoryService(client)
        return self

    def __exit__(self, *_exc: object) -> None:
        client = self.client
        audit = self._audit
        self.client = None
        self.capabilities = None
        self.inventory = None
        self._audit = None
        try:
            if audit is not None:
                audit.close()
        finally:
            if client is not None:
                client.close()

    def services(
        self,
    ) -> tuple[SubprocessAppServer, CapabilityMatrix, InventoryService]:
        if self.client is None or self.capabilities is None or self.inventory is None:
            raise RuntimeError("workflow session is not open")
        return self.client, self.capabilities, self.inventory


class ApplicationWorkflows:
    """Small use-case Interface over deep safety-oriented implementations."""

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        request_timeout: float = 45.0,
        connection_factory: ConnectionFactory = connect_and_probe,
        backup_backend_factory: Callable[[], CipherBackend] = AgeBackend,
    ) -> None:
        self.paths = paths or get_paths()
        self.request_timeout = request_timeout
        self.connection_factory = connection_factory
        self.backup_backend_factory = backup_backend_factory

    def session(
        self,
        *,
        experimental_api: bool = False,
        request_timeout: float | None = None,
    ) -> WorkflowSession:
        return WorkflowSession(
            paths=self.paths,
            connection_factory=self.connection_factory,
            request_timeout=request_timeout or self.request_timeout,
            experimental_api=experimental_api,
        )

    def list_threads(
        self,
        *,
        criteria: InventoryFilter | None = None,
        include_active: bool = True,
        include_archived: bool = True,
    ) -> InventoryResult:
        with self.session() as session:
            _client, capabilities, inventory = session.services()
            snapshots = inventory.list(
                criteria=criteria,
                include_active=include_active,
                include_archived=include_archived,
                include_turns=False,
            )
            return InventoryResult(capabilities, snapshots)

    def save_plan(self, plan: PlanModel) -> Path:
        """Persist an already-validated immutable plan through the shared Seam."""

        return PlanStore(self.paths).save(plan)

    def read_thread(self, thread_id: str, *, include_turns: bool = True) -> ThreadReadResult:
        with self.session() as session:
            _client, capabilities, inventory = session.services()
            return ThreadReadResult(
                capabilities,
                inventory.read(thread_id, include_turns=include_turns),
            )

    def prepare_cleanup_plan(
        self,
        *,
        action: PlanAction,
        policy: CleanupPolicy,
        criteria: InventoryFilter | None = None,
    ) -> PreparedAction:
        if action not in {PlanAction.ARCHIVE, PlanAction.UNARCHIVE}:
            raise ValueError("cleanup plan action must be archive or unarchive")
        with self.session() as session:
            _client, capabilities, inventory = session.services()
            planner = CleanupPlanner(policy)
            summaries = inventory.list(include_turns=False)
            if action is PlanAction.ARCHIVE:
                hydration_ids = planner.archive_hydration_ids(summaries, criteria=criteria)
            else:
                hydration_ids = planner.unarchive_hydration_ids(summaries, criteria=criteria)
            snapshots = inventory.hydrate(summaries, hydration_ids) if hydration_ids else summaries
            plan = (
                planner.plan_archive(snapshots, capabilities, criteria=criteria)
                if action is PlanAction.ARCHIVE
                else planner.plan_unarchive(snapshots, capabilities, criteria=criteria)
            )
            return PreparedAction(plan, session.plans.save(plan))

    def prepare_selected_archive(self, selected_ids: tuple[str, ...]) -> PreparedAction:
        with self.session() as session:
            _client, capabilities, inventory = session.services()
            snapshots = inventory.list_for_targets(selected_ids)
            plan = CleanupPlanner().plan_selected_archive(
                snapshots,
                capabilities,
                selected_ids,
            )
            return PreparedAction(plan, session.plans.save(plan))

    def prepare_selected_purge(self, selected_ids: tuple[str, ...]) -> PreparedAction:
        with self.session(experimental_api=True) as session:
            _client, capabilities, inventory = session.services()
            snapshots = inventory.list_for_targets(selected_ids)
            plan = CleanupPlanner().plan_selected_purge(
                snapshots,
                capabilities,
                session.audit,
                selected_ids,
            )
            return PreparedAction(plan, session.plans.save(plan))

    def prepare_purge_plan(self, *, policy: CleanupPolicy | None = None) -> PreparedAction:
        """Prepare the global manual purge plan; audit eligibility needs full content."""

        with self.session() as session:
            _client, capabilities, inventory = session.services()
            snapshots = inventory.list(include_turns=True)
            plan = CleanupPlanner(policy).plan_purge(snapshots, capabilities, session.audit)
            return PreparedAction(plan, session.plans.save(plan))

    def rename_thread(self, thread_id: str, new_name: str) -> ActionExecutionResult:
        with self.session() as session:
            client, capabilities, inventory = session.services()
            snapshots = inventory.list_for_targets((thread_id,))
            plan = CleanupPlanner().plan_rename(
                snapshots,
                capabilities,
                thread_id=thread_id,
                new_name=new_name,
            )
            session.plans.save(plan)
            completed = CleanupExecutor(
                client=client,
                inventory=inventory,
                capabilities=capabilities,
                audit=session.audit,
            ).apply(plan)
            return ActionExecutionResult(plan, completed)

    def apply_action(
        self,
        plan: ActionPlan,
        *,
        confirmation: str,
        permanent_phrase: str | None = None,
    ) -> ActionExecutionResult:
        with self.session(experimental_api=plan.action is PlanAction.PURGE) as session:
            client, capabilities, inventory = session.services()
            completed = CleanupExecutor(
                client=client,
                inventory=inventory,
                capabilities=capabilities,
                audit=session.audit,
            ).apply(
                plan,
                confirmation=confirmation,
                permanent_phrase=permanent_phrase,
            )
            return ActionExecutionResult(plan, completed)

    def reconcile_archive(self, plan: ActionPlan) -> ActionExecutionResult:
        with self.session() as session:
            client, capabilities, inventory = session.services()
            completed = CleanupExecutor(
                client=client,
                inventory=inventory,
                capabilities=capabilities,
                audit=session.audit,
            ).reconcile_native_archive(plan)
            return ActionExecutionResult(plan, completed)

    def create_backup(
        self,
        destination: Path,
        *,
        thread_ids: tuple[str, ...],
        encryption: EncryptionSpec,
        verification_decryption: DecryptionSpec,
        include_raw: bool = True,
        expand_descendants: bool = True,
    ) -> BackupCreationResult:
        with self.session() as session:
            client, _capabilities, inventory = session.services()
            indexed = inventory.list_for_targets(thread_ids)
            covered_ids = (
                target_closure_ids(indexed, thread_ids)
                if expand_descendants
                else tuple(dict.fromkeys(thread_ids))
            )
            by_id = {snapshot.id: snapshot for snapshot in indexed}
            snapshots = tuple(by_id[thread_id] for thread_id in covered_ids)
            manifest = BackupService(
                client=client,
                paths=self.paths,
                backend=self.backup_backend_factory(),
                audit=session.audit,
            ).create(
                destination,
                snapshots=snapshots,
                encryption=encryption,
                verification_decryption=verification_decryption,
                include_raw=include_raw,
            )
            return BackupCreationResult(manifest, covered_ids)

    def apply_trim(self, plan: TrimPlan) -> str:
        with self.session() as session:
            client, capabilities, inventory = session.services()
            return TrimExecutor(
                client=client,
                inventory=inventory,
                capabilities=capabilities,
                audit=session.audit,
            ).apply(plan)

    def scan_sensitive_threads(
        self,
        thread_ids: tuple[str, ...],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[tuple[int, int]], Any] | None = None,
    ) -> SensitiveScanBatch:
        matches: dict[str, SensitiveScanResult] = {}
        scanned = 0
        processed = 0
        failed = 0
        total = len(thread_ids)
        if not thread_ids:
            return SensitiveScanBatch(matches, scanned, failed)

        worker_count = min(_SENSITIVE_SCAN_MAX_WORKERS, total)
        max_pending = worker_count
        pending: dict[Future[SensitiveScanResult], str] = {}

        def report_processed() -> None:
            if progress is not None:
                progress((processed, total))

        def consume(done: set[Future[SensitiveScanResult]]) -> bool:
            """Merge completed local scans on the producer worker thread."""

            nonlocal scanned, processed, failed
            for future in done:
                thread_id = pending.pop(future)
                try:
                    result = future.result()
                except SensitiveScanCancelled:
                    return False
                except (RuntimeError, ValueError):
                    failed += 1
                else:
                    scanned += 1
                    if result.has_findings:
                        matches[thread_id] = result
                processed += 1
                report_processed()
            return True

        def cancelled_result() -> SensitiveScanBatch:
            for future in pending:
                future.cancel()
            return SensitiveScanBatch(matches, scanned, failed, cancelled=True)

        executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="csm-sensitive-scan",
        )
        try:
            with self.session() as session:
                _client, _capabilities, inventory = session.services()
                for thread_id in thread_ids:
                    if cancelled():
                        return cancelled_result()
                    while len(pending) >= max_pending:
                        done, _not_done = wait(
                            tuple(pending),
                            timeout=0.05,
                            return_when=FIRST_COMPLETED,
                        )
                        if not done:
                            if cancelled():
                                return cancelled_result()
                            continue
                        if not consume(done):
                            return cancelled_result()
                    try:
                        snapshot = inventory.read(thread_id, include_turns=True)
                    except (RuntimeError, ValueError):
                        failed += 1
                        processed += 1
                        report_processed()
                    else:
                        pending[
                            executor.submit(
                                scan_sensitive_snapshot,
                                snapshot,
                                cancelled=cancelled,
                            )
                        ] = thread_id

                    if pending:
                        done, _not_done = wait(
                            tuple(pending),
                            timeout=0,
                            return_when=FIRST_COMPLETED,
                        )
                        if done and not consume(done):
                            return cancelled_result()

            while pending:
                if cancelled():
                    return cancelled_result()
                done, _not_done = wait(
                    tuple(pending),
                    timeout=0.05,
                    return_when=FIRST_COMPLETED,
                )
                if done and not consume(done):
                    return cancelled_result()
            return SensitiveScanBatch(matches, scanned, failed)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
