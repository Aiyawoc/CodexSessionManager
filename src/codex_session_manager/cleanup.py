"""Cleanup planning and guarded execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from codex_session_manager.app_server import RequestTimeout, SubprocessAppServer
from codex_session_manager.audit import AuditStore
from codex_session_manager.hashing import utc_now
from codex_session_manager.inventory import (
    InventoryFilter,
    InventoryService,
    _parent_ids,
    matches_filter,
)
from codex_session_manager.models import (
    ActionPlan,
    CapabilityMatrix,
    PlanAction,
    PlanTarget,
    RiskLevel,
    ThreadSnapshot,
    ThreadStatus,
)

DEFAULT_STALE_DAYS: Final[int] = 90
DEFAULT_PURGE_DELAY_DAYS: Final[int] = 14
MAX_ROOTS: Final[int] = 100
SAFE_INACTIVE_STATUSES: Final[frozenset[ThreadStatus]] = frozenset(
    {ThreadStatus.IDLE, ThreadStatus.NOT_LOADED}
)


@dataclass(frozen=True, slots=True)
class CleanupPolicy:
    stale_after: timedelta = timedelta(days=DEFAULT_STALE_DAYS)
    purge_delay: timedelta = timedelta(days=DEFAULT_PURGE_DELAY_DAYS)
    maximum_roots: int = MAX_ROOTS


def _top_level_candidates(
    candidates: list[ThreadSnapshot], all_snapshots: dict[str, ThreadSnapshot]
) -> list[ThreadSnapshot]:
    candidate_ids = {item.id for item in candidates}
    roots: list[ThreadSnapshot] = []
    for candidate in candidates:
        parents = list(_parent_ids(candidate))
        if any(parent in candidate_ids for parent in parents):
            continue
        # If any known ancestor is also a candidate, the archive/delete cascade
        # must be represented by that ancestor only.
        visited: set[str] = set()
        queue = parents
        nested = False
        while queue:
            parent = queue.pop()
            if parent in visited:
                continue
            visited.add(parent)
            if parent in candidate_ids:
                nested = True
                break
            ancestor = all_snapshots.get(parent)
            if ancestor is not None:
                queue.extend(_parent_ids(ancestor))
        if not nested:
            roots.append(candidate)
    return roots


def _non_overlapping_roots(roots: list[ThreadSnapshot]) -> list[ThreadSnapshot]:
    """Reject ambiguous DAG roots whose descendant closures overlap."""

    closures = [set((root.id, *root.spawned_descendant_ids)) for root in roots]
    ambiguous: set[int] = set()
    for left_index, left in enumerate(closures):
        for right_index in range(left_index + 1, len(closures)):
            if left & closures[right_index]:
                ambiguous.update((left_index, right_index))
    return [root for index, root in enumerate(roots) if index not in ambiguous]


class CleanupPlanner:
    def __init__(self, policy: CleanupPolicy | None = None) -> None:
        self.policy = policy or CleanupPolicy()

    def plan_archive(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        *,
        now: datetime | None = None,
        criteria: InventoryFilter | None = None,
    ) -> ActionPlan:
        effective_now = (now or utc_now()).astimezone(UTC)
        cutoff = effective_now - self.policy.stale_after
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        candidates: list[ThreadSnapshot] = []
        for snapshot in snapshots:
            if (
                snapshot.archived
                or snapshot.pinned
                or snapshot.ephemeral
                or not snapshot.mapping_complete
                or not snapshot.content_complete
            ):
                continue
            if snapshot.status not in SAFE_INACTIVE_STATUSES:
                continue
            if snapshot.updated_at is None or snapshot.updated_at >= cutoff:
                continue
            candidates.append(snapshot)
        candidate_ids = {snapshot.id for snapshot in candidates}
        roots = _non_overlapping_roots(
            [
                root
                for root in _top_level_candidates(candidates, all_snapshots)
                if {root.id, *root.spawned_descendant_ids} <= candidate_ids
                and (criteria is None or matches_filter(root, criteria))
            ]
        )
        if len(roots) > self.policy.maximum_roots:
            roots = sorted(
                roots, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC)
            )[: self.policy.maximum_roots]
        targets = tuple(self._target(root, all_snapshots, cutoff) for root in roots)
        return ActionPlan.create(
            action=PlanAction.ARCHIVE,
            capability_fingerprint=capabilities.fingerprint,
            targets=targets,
            prerequisites=(
                "verified encrypted backup covering every affected snapshot",
                "all affected threads remain non-active and unpinned",
                "descendant closure and App Server capability fingerprint remain unchanged",
            ),
            options={"stale_before": cutoff.isoformat(), "automatic_ceiling": "archive"},
        )

    def plan_selected_archive(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        selected_ids: tuple[str, ...],
    ) -> ActionPlan:
        """Plan an explicitly selected archive batch without an age policy.

        Explicit selection never weakens the safety gates: every spawned
        descendant must still be present, complete, inactive, unpinned, and
        non-ephemeral.  The executor also requires a current verified backup.
        """

        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self._explicit_roots(selected_ids, all_snapshots)
        targets: list[PlanTarget] = []
        for root in roots:
            closure = self._resolved_closure(root, all_snapshots)
            for snapshot in closure:
                reason = self._archive_block_reason(snapshot)
                if reason:
                    raise ValueError(f"selected archive blocked for {snapshot.id}: {reason}")
            targets.append(
                self._explicit_target(root, all_snapshots, "explicit human archive selection")
            )
        return ActionPlan.create(
            action=PlanAction.ARCHIVE,
            capability_fingerprint=capabilities.fingerprint,
            targets=tuple(targets),
            prerequisites=(
                "verified encrypted backup covering every affected snapshot",
                "all affected threads remain non-active and unpinned",
                "descendant closure and App Server capability fingerprint remain unchanged",
            ),
            options={"manual_selection": True, "automatic_ceiling": "archive"},
        )

    def plan_rename(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        *,
        thread_id: str,
        new_name: str,
    ) -> ActionPlan:
        """Plan a reversible title change against a full management snapshot."""

        normalized_name = new_name.strip()
        if not normalized_name:
            raise ValueError("new conversation name must not be empty")
        if len(normalized_name) > 200:
            raise ValueError("new conversation name exceeds 200 characters")
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self._explicit_roots((thread_id,), all_snapshots)
        root = roots[0]
        for snapshot in self._resolved_closure(root, all_snapshots):
            if snapshot.status not in SAFE_INACTIVE_STATUSES:
                raise ValueError(f"selected rename blocked for active thread: {snapshot.id}")
            if snapshot.pinned or snapshot.ephemeral:
                raise ValueError(f"selected rename blocked for protected thread: {snapshot.id}")
            if not snapshot.mapping_complete or not snapshot.content_complete:
                raise ValueError(f"selected rename lacks complete mapping: {snapshot.id}")
        if root.title == normalized_name:
            raise ValueError("new conversation name is unchanged")
        return ActionPlan.create(
            action=PlanAction.RENAME,
            capability_fingerprint=capabilities.fingerprint,
            targets=(
                self._explicit_target(root, all_snapshots, "explicit human rename selection"),
            ),
            prerequisites=(
                "the selected conversation remains inactive",
                "descendant closure and App Server capability fingerprint remain unchanged",
            ),
            options={"new_name": normalized_name, "manual_selection": True},
        )

    def plan_unarchive(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        *,
        criteria: InventoryFilter | None = None,
    ) -> ActionPlan:
        selected = [
            snapshot
            for snapshot in snapshots
            if snapshot.archived
            and not snapshot.ephemeral
            and snapshot.mapping_complete
            and snapshot.content_complete
        ]
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        selected = _non_overlapping_roots(_top_level_candidates(selected, all_snapshots))
        if criteria is not None:
            selected = [snapshot for snapshot in selected if matches_filter(snapshot, criteria)]
        targets = tuple(
            self._target(snapshot, all_snapshots, utc_now())
            for snapshot in selected[: self.policy.maximum_roots]
        )
        return ActionPlan.create(
            action=PlanAction.UNARCHIVE,
            capability_fingerprint=capabilities.fingerprint,
            targets=targets,
            prerequisites=("descendant closure remains unchanged",),
        )

    def plan_purge(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        audit: AuditStore,
        *,
        now: datetime | None = None,
    ) -> ActionPlan:
        effective_now = (now or utc_now()).astimezone(UTC)
        audit.verify_chain()
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        eligible: list[ThreadSnapshot] = []
        for snapshot in snapshots:
            if (
                not snapshot.archived
                or snapshot.pinned
                or snapshot.ephemeral
                or snapshot.status not in SAFE_INACTIVE_STATUSES
                or not snapshot.mapping_complete
                or not snapshot.content_complete
            ):
                continue
            trusted = audit.trusted_archive(snapshot.id)
            if trusted is None or effective_now - trusted.archived_at < self.policy.purge_delay:
                continue
            evidence = audit.verified_backup(
                snapshot.id,
                snapshot.backup_fingerprint,
                manifest_sha256=trusted.manifest_sha256,
            )
            if evidence is None or not evidence.is_current():
                continue
            eligible.append(snapshot)
        eligible_ids = {snapshot.id for snapshot in eligible}
        roots = _non_overlapping_roots(
            [
                root
                for root in _top_level_candidates(eligible, all_snapshots)
                if {root.id, *root.spawned_descendant_ids} <= eligible_ids
            ]
        )[: self.policy.maximum_roots]
        targets = tuple(self._target(root, all_snapshots, effective_now) for root in roots)
        return ActionPlan.create(
            action=PlanAction.PURGE,
            capability_fingerprint=capabilities.fingerprint,
            targets=targets,
            prerequisites=(
                f"CSM-trusted archive age is at least {self.policy.purge_delay.days} days",
                "verified encrypted backup covers every affected snapshot",
                "no other Codex process is running against the data root",
                "human supplies the exact plan id and permanent-deletion phrase",
            ),
            options={"manual_only": True, "minimum_archive_days": self.policy.purge_delay.days},
        )

    def plan_selected_purge(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        audit: AuditStore,
        selected_ids: tuple[str, ...],
        *,
        now: datetime | None = None,
    ) -> ActionPlan:
        """Plan permanent deletion for explicit roots after every purge gate passes."""

        effective_now = (now or utc_now()).astimezone(UTC)
        audit.verify_chain()
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self._explicit_roots(selected_ids, all_snapshots)
        targets: list[PlanTarget] = []
        for root in roots:
            closure = self._resolved_closure(root, all_snapshots)
            for snapshot in closure:
                if (
                    not snapshot.archived
                    or snapshot.pinned
                    or snapshot.ephemeral
                    or snapshot.status not in SAFE_INACTIVE_STATUSES
                    or not snapshot.mapping_complete
                    or not snapshot.content_complete
                ):
                    raise ValueError(
                        f"selected permanent deletion is not safely archived: {snapshot.id}"
                    )
                trusted = audit.trusted_archive(snapshot.id)
                if trusted is None or effective_now - trusted.archived_at < self.policy.purge_delay:
                    raise ValueError(
                        f"selected permanent deletion requires {self.policy.purge_delay.days} "
                        f"days of CSM-trusted archive history: {snapshot.id}"
                    )
                evidence = audit.verified_backup(
                    snapshot.id,
                    snapshot.backup_fingerprint,
                    manifest_sha256=trusted.manifest_sha256,
                )
                if evidence is None or not evidence.is_current():
                    raise ValueError(
                        f"selected permanent deletion lacks an archive-bound verified backup: "
                        f"{snapshot.id}"
                    )
            targets.append(
                self._explicit_target(
                    root, all_snapshots, "explicit human permanent-deletion selection"
                )
            )
        return ActionPlan.create(
            action=PlanAction.PURGE,
            capability_fingerprint=capabilities.fingerprint,
            targets=tuple(targets),
            prerequisites=(
                f"CSM-trusted archive age is at least {self.policy.purge_delay.days} days",
                "verified encrypted backup covers every affected snapshot",
                "no other Codex process is running against the data root",
                "human supplies the exact plan id and permanent-deletion phrase",
            ),
            options={
                "manual_only": True,
                "manual_selection": True,
                "minimum_archive_days": self.policy.purge_delay.days,
            },
        )

    def _explicit_roots(
        self,
        selected_ids: tuple[str, ...],
        snapshots: dict[str, ThreadSnapshot],
    ) -> list[ThreadSnapshot]:
        unique_ids = tuple(dict.fromkeys(selected_ids))
        if not unique_ids:
            raise ValueError("at least one conversation must be selected")
        missing = [thread_id for thread_id in unique_ids if thread_id not in snapshots]
        if missing:
            raise ValueError(
                "selected conversations are no longer available: " + ", ".join(missing)
            )
        selected = [snapshots[thread_id] for thread_id in unique_ids]
        roots = _non_overlapping_roots(_top_level_candidates(selected, snapshots))
        if not roots:
            raise ValueError("selected conversation closures overlap or cannot be resolved")
        if len(roots) > self.policy.maximum_roots:
            raise ValueError(
                f"selected batch exceeds the {self.policy.maximum_roots}-root safety limit"
            )
        covered = {
            thread_id for root in roots for thread_id in (root.id, *root.spawned_descendant_ids)
        }
        if not set(unique_ids) <= covered:
            raise ValueError("selected conversation graph cannot be represented safely")
        return roots

    @staticmethod
    def _resolved_closure(
        root: ThreadSnapshot, snapshots: dict[str, ThreadSnapshot]
    ) -> tuple[ThreadSnapshot, ...]:
        closure_ids = (root.id, *root.spawned_descendant_ids)
        missing = [thread_id for thread_id in closure_ids if thread_id not in snapshots]
        if missing:
            raise ValueError(
                f"descendant closure is incomplete for {root.id}: " + ", ".join(missing)
            )
        return tuple(snapshots[thread_id] for thread_id in closure_ids)

    @staticmethod
    def _archive_block_reason(snapshot: ThreadSnapshot) -> str | None:
        if snapshot.archived:
            return "conversation is already archived"
        if snapshot.pinned:
            return "conversation is pinned"
        if snapshot.ephemeral:
            return "ephemeral conversation cannot be managed"
        if snapshot.status not in SAFE_INACTIVE_STATUSES:
            return "conversation is active or in an unsafe state"
        if not snapshot.mapping_complete or not snapshot.content_complete:
            return "conversation mapping/content is incomplete"
        return None

    @staticmethod
    def _explicit_target(
        root: ThreadSnapshot,
        snapshots: dict[str, ThreadSnapshot],
        reason: str,
    ) -> PlanTarget:
        closure = tuple(thread_id for thread_id in (root.id, *root.spawned_descendant_ids))
        return PlanTarget(
            root_thread_id=root.id,
            affected_thread_ids=closure,
            snapshot_fingerprints={
                thread_id: snapshots[thread_id].management_fingerprint for thread_id in closure
            },
            reasons=(reason,),
            risk=RiskLevel.MEDIUM if len(closure) > 1 else RiskLevel.LOW,
        )

    @staticmethod
    def _target(
        root: ThreadSnapshot,
        snapshots: dict[str, ThreadSnapshot],
        cutoff: datetime,
    ) -> PlanTarget:
        closure = tuple(
            thread_id
            for thread_id in (root.id, *root.spawned_descendant_ids)
            if thread_id in snapshots
        )
        reasons = ["root selected by policy"]
        if root.updated_at:
            reasons.append(
                f"last activity {root.updated_at.isoformat()} before {cutoff.isoformat()}"
            )
        risk = RiskLevel.MEDIUM if len(closure) > 1 else RiskLevel.LOW
        return PlanTarget(
            root_thread_id=root.id,
            affected_thread_ids=closure,
            snapshot_fingerprints={
                thread_id: snapshots[thread_id].management_fingerprint for thread_id in closure
            },
            reasons=tuple(reasons),
            risk=risk,
        )


class ProcessGuard:
    """Conservatively detect other local Codex processes before purge."""

    @staticmethod
    def assert_no_other_codex_processes(*, controlled_pid: int | None = None) -> None:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        blockers: list[str] = []
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            pid_text, _, command = stripped.partition(" ")
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if controlled_pid is not None and pid == controlled_pid:
                continue
            lowered = command.casefold()
            is_codex = (
                "/codex.app/contents/" in lowered
                or lowered.endswith("/codex")
                or " codex app-server" in lowered
                or "/bin/codex " in lowered
            )
            if is_codex and "codex_session_manager" not in lowered:
                blockers.append(f"{pid} {command}")
        if blockers:
            preview = "; ".join(blockers[:5])
            raise RuntimeError(f"permanent deletion blocked by running Codex processes: {preview}")


class CleanupExecutor:
    """Apply one already-sealed plan after re-reading all safety evidence."""

    def __init__(
        self,
        *,
        client: SubprocessAppServer,
        inventory: InventoryService,
        capabilities: CapabilityMatrix,
        audit: AuditStore,
    ) -> None:
        self.client = client
        self.inventory = inventory
        self.capabilities = capabilities
        self.audit = audit

    def apply(
        self,
        plan: ActionPlan,
        *,
        confirmation: str | None = None,
        permanent_phrase: str | None = None,
    ) -> tuple[str, ...]:
        plan.verify()
        self.audit.verify_chain()
        if plan.capability_fingerprint != self.capabilities.fingerprint:
            raise ValueError("App Server capability drift invalidated the plan")
        method = {
            PlanAction.ARCHIVE: "thread/archive",
            PlanAction.UNARCHIVE: "thread/unarchive",
            PlanAction.PURGE: "thread/delete",
            PlanAction.RENAME: "thread/name/set",
        }.get(plan.action)
        if method is None:
            raise ValueError(f"CleanupExecutor cannot apply {plan.action.value}")
        self.capabilities.require_write(method)
        current = self.inventory.list(
            include_active=True, include_archived=True, include_turns=True
        )
        current_by_id = self._verify_snapshot_drift(plan, current)
        if plan.action in {PlanAction.ARCHIVE, PlanAction.PURGE}:
            self._verify_backup_gate(plan, current_by_id)
        if plan.action is PlanAction.PURGE:
            if confirmation != plan.plan_id:
                raise ValueError("purge confirmation must equal the exact plan id")
            if permanent_phrase != "PERMANENTLY DELETE CODEX TASKS":
                raise ValueError("missing permanent-deletion confirmation phrase")
            self._verify_purge_gate(plan, plan.targets, current_by_id)
            self.capabilities.require_write("thread/backgroundTerminals/list")
            self.capabilities.require_write("thread/loaded/list")
            background_processes = {
                thread_id: self.client.background_terminals(thread_id)
                for target in plan.targets
                for thread_id in target.affected_thread_ids
            }
            occupied = {
                thread_id: terminals
                for thread_id, terminals in background_processes.items()
                if terminals
            }
            if occupied:
                raise RuntimeError(
                    "permanent deletion blocked by background terminals: "
                    + ", ".join(sorted(occupied))
                )
            ProcessGuard.assert_no_other_codex_processes(controlled_pid=self.client.pid)
        loaded = (
            set(self.client.loaded_thread_ids())
            if self.capabilities.supports("thread/loaded/list")
            else set()
        )
        affected = {
            thread_id for target in plan.targets for thread_id in target.affected_thread_ids
        }
        if loaded & affected:
            raise RuntimeError(
                f"affected threads are loaded: {', '.join(sorted(loaded & affected))}"
            )

        self.audit.begin_operation(plan_sha256=plan.plan_sha256, action=plan.action.value)
        completed: list[str] = []
        try:
            if plan.action is PlanAction.UNARCHIVE:
                for thread_id in sorted(affected):
                    self.audit.invalidate_trusted_archive(
                        thread_id=thread_id, plan_sha256=plan.plan_sha256
                    )
            for target in plan.targets:
                if plan.action is PlanAction.PURGE:
                    fresh = self.inventory.list(
                        include_active=True, include_archived=True, include_turns=True
                    )
                    fresh_by_id = {snapshot.id: snapshot for snapshot in fresh}
                    self._verify_target_drift(plan, target, fresh_by_id)
                    self._verify_backup_gate(plan, fresh_by_id, targets=(target,))
                    self._verify_purge_gate(plan, (target,), fresh_by_id)
                    fresh_loaded = (
                        set(self.client.loaded_thread_ids())
                        if self.capabilities.supports("thread/loaded/list")
                        else set()
                    )
                    occupied_loaded = fresh_loaded & set(target.affected_thread_ids)
                    if occupied_loaded:
                        raise RuntimeError(
                            "affected threads became loaded: " + ", ".join(sorted(occupied_loaded))
                        )
                    fresh_terminals = {
                        thread_id: self.client.background_terminals(thread_id)
                        for thread_id in target.affected_thread_ids
                    }
                    occupied_terminals = {
                        thread_id: terminals
                        for thread_id, terminals in fresh_terminals.items()
                        if terminals
                    }
                    if occupied_terminals:
                        raise RuntimeError(
                            "permanent deletion blocked by newly opened background terminals: "
                            + ", ".join(sorted(occupied_terminals))
                        )
                    ProcessGuard.assert_no_other_codex_processes(controlled_pid=self.client.pid)
                self._apply_root(plan, target.root_thread_id)
                completed.append(target.root_thread_id)
            self._verify_result(plan, affected)
            if plan.action is PlanAction.ARCHIVE:
                self._record_archives(plan, current_by_id)
            self.audit.finish_operation(plan_sha256=plan.plan_sha256, status="succeeded")
            self.audit.append(
                event_type=f"{plan.action.value}.apply",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(sorted(affected)),
                details={"root_count": len(plan.targets)},
            )
            return tuple(completed)
        except BaseException as exc:
            self.audit.finish_operation(
                plan_sha256=plan.plan_sha256, status="failed", error=str(exc)
            )
            self.audit.append(
                event_type=f"{plan.action.value}.apply",
                actor="human",
                result="failed",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(sorted(affected)),
                details={"error": str(exc), "completed_roots": completed},
            )
            raise

    def reconcile_native_archive(self, plan: ActionPlan) -> tuple[str, ...]:
        """Audit an archive applied by Codex App's native task tool.

        This performs no Codex write.  It is intentionally limited to archive
        plans and requires the same plan, capability, closure, drift, backup,
        and postcondition evidence as ``apply``.
        """

        plan.verify()
        self.audit.verify_chain()
        if plan.action is not PlanAction.ARCHIVE:
            raise ValueError("native reconciliation only supports archive plans")
        if plan.capability_fingerprint != self.capabilities.fingerprint:
            raise ValueError("App Server capability drift invalidated the plan")
        current = self.inventory.list(
            include_active=True, include_archived=True, include_turns=True
        )
        current_by_id = self._verify_snapshot_drift(
            plan, current, allow_native_archive_transition=True
        )
        self._verify_backup_gate(plan, current_by_id)
        affected = {
            thread_id for target in plan.targets for thread_id in target.affected_thread_ids
        }
        by_id = {snapshot.id: snapshot for snapshot in current}
        unresolved = [
            thread_id
            for thread_id in affected
            if thread_id not in by_id or not by_id[thread_id].archived
        ]
        if unresolved:
            raise RuntimeError(
                "native archive postcondition unresolved for: " + ", ".join(sorted(unresolved))
            )
        self._record_archives(plan, current_by_id)
        self.audit.append(
            event_type="archive.reconcile-native",
            actor="codex-native-task-tool",
            result="succeeded",
            plan_sha256=plan.plan_sha256,
            target_ids=tuple(sorted(affected)),
            details={"root_count": len(plan.targets), "codex_write_performed_by_csm": False},
        )
        return tuple(target.root_thread_id for target in plan.targets)

    def _apply_root(self, plan: ActionPlan, thread_id: str) -> None:
        try:
            if plan.action is PlanAction.ARCHIVE:
                self.client.archive_thread(thread_id)
            elif plan.action is PlanAction.UNARCHIVE:
                self.client.unarchive_thread(thread_id)
            elif plan.action is PlanAction.PURGE:
                self.client.delete_thread(thread_id)
            elif plan.action is PlanAction.RENAME:
                new_name = plan.options.get("new_name")
                if not isinstance(new_name, str) or not new_name:
                    raise ValueError("rename plan lacks a non-empty new_name")
                self.client.rename_thread(thread_id, new_name)
        except RequestTimeout as exc:
            # Never retry.  The postcondition query in _verify_result determines
            # whether the operation committed; an unresolved state stays failed.
            if not exc.may_have_committed:
                raise

    @staticmethod
    def _verify_snapshot_drift(
        plan: ActionPlan,
        current_snapshots: tuple[ThreadSnapshot, ...],
        *,
        allow_native_archive_transition: bool = False,
    ) -> dict[str, ThreadSnapshot]:
        by_id = {snapshot.id: snapshot for snapshot in current_snapshots}
        for target in plan.targets:
            CleanupExecutor._verify_target_drift(
                plan,
                target,
                by_id,
                allow_native_archive_transition=allow_native_archive_transition,
            )
        return by_id

    @staticmethod
    def _verify_target_drift(
        plan: ActionPlan,
        target: PlanTarget,
        by_id: dict[str, ThreadSnapshot],
        *,
        allow_native_archive_transition: bool = False,
    ) -> None:
        root = by_id.get(target.root_thread_id)
        current_closure = (
            (target.root_thread_id, *root.spawned_descendant_ids) if root is not None else ()
        )
        if set(current_closure) != set(target.affected_thread_ids):
            raise ValueError(f"descendant closure drift for {target.root_thread_id}")
        for thread_id, expected in target.snapshot_fingerprints.items():
            snapshot = by_id.get(thread_id)
            if snapshot is None:
                raise ValueError(f"snapshot drift for {thread_id}")
            observed = snapshot.management_fingerprint
            if allow_native_archive_transition and plan.action is PlanAction.ARCHIVE:
                observed = snapshot.model_copy(update={"archived": False}).management_fingerprint
            if observed != expected:
                raise ValueError(f"snapshot drift for {thread_id}")
            if snapshot.status not in SAFE_INACTIVE_STATUSES:
                raise ValueError(f"thread is not safely inactive: {thread_id}")
            if snapshot.pinned:
                raise ValueError(f"thread became pinned: {thread_id}")
            if snapshot.ephemeral:
                raise ValueError(f"ephemeral thread cannot be managed: {thread_id}")
            if plan.action is PlanAction.ARCHIVE and not allow_native_archive_transition:
                if snapshot.archived:
                    raise ValueError(f"thread is already archived: {thread_id}")
            elif plan.action in {PlanAction.UNARCHIVE, PlanAction.PURGE} and not snapshot.archived:
                raise ValueError(f"thread is no longer archived: {thread_id}")

    def _verify_backup_gate(
        self,
        plan: ActionPlan,
        current_by_id: dict[str, ThreadSnapshot],
        *,
        targets: tuple[PlanTarget, ...] | None = None,
    ) -> None:
        for target in targets or plan.targets:
            for thread_id in target.affected_thread_ids:
                snapshot = current_by_id.get(thread_id)
                if snapshot is None:
                    raise ValueError(f"backup gate cannot resolve {thread_id}")
                evidence = self.audit.verified_backup(thread_id, snapshot.backup_fingerprint)
                if evidence is None or not evidence.is_current():
                    raise ValueError(f"no verified encrypted backup covers {thread_id}")

    def _verify_purge_gate(
        self,
        plan: ActionPlan,
        targets: tuple[PlanTarget, ...],
        current_by_id: dict[str, ThreadSnapshot],
    ) -> None:
        minimum_days = plan.options.get("minimum_archive_days")
        if not isinstance(minimum_days, int) or minimum_days < DEFAULT_PURGE_DELAY_DAYS:
            raise ValueError("purge plan has an invalid trusted-archive threshold")
        now = utc_now()
        for target in targets:
            for thread_id in target.affected_thread_ids:
                snapshot = current_by_id.get(thread_id)
                if snapshot is None or not snapshot.archived:
                    raise ValueError(f"thread is no longer archived: {thread_id}")
                trusted = self.audit.trusted_archive(thread_id)
                if trusted is None or now - trusted.archived_at < timedelta(days=minimum_days):
                    raise ValueError(f"trusted archive age is insufficient: {thread_id}")
                evidence = self.audit.verified_backup(
                    thread_id,
                    snapshot.backup_fingerprint,
                    manifest_sha256=trusted.manifest_sha256,
                )
                if evidence is None or not evidence.is_current():
                    raise ValueError(
                        f"archive-bound verified backup is no longer current: {thread_id}"
                    )

    def _verify_result(self, plan: ActionPlan, affected: set[str]) -> None:
        current = self.inventory.list(include_active=True, include_archived=True)
        by_id = {snapshot.id: snapshot for snapshot in current}
        if plan.action is PlanAction.ARCHIVE:
            unresolved = [
                thread_id
                for thread_id in affected
                if not by_id.get(thread_id) or not by_id[thread_id].archived
            ]
        elif plan.action is PlanAction.UNARCHIVE:
            unresolved = [
                thread_id
                for thread_id in affected
                if not by_id.get(thread_id) or by_id[thread_id].archived
            ]
        elif plan.action is PlanAction.PURGE:
            unresolved = [thread_id for thread_id in affected if thread_id in by_id]
        else:
            new_name = plan.options.get("new_name")
            unresolved = [
                target.root_thread_id
                for target in plan.targets
                if target.root_thread_id not in by_id
                or by_id[target.root_thread_id].title != new_name
            ]
        if unresolved:
            raise RuntimeError(
                f"operation postcondition unresolved for: {', '.join(sorted(unresolved))}; no retry was attempted"
            )

    def _record_archives(self, plan: ActionPlan, current_by_id: dict[str, ThreadSnapshot]) -> None:
        for target in plan.targets:
            for thread_id in target.affected_thread_ids:
                snapshot = current_by_id.get(thread_id)
                if snapshot is None:
                    raise RuntimeError(f"archive source disappeared for {thread_id}")
                evidence = self.audit.verified_backup(thread_id, snapshot.backup_fingerprint)
                if evidence is None:
                    raise RuntimeError(f"backup evidence disappeared for {thread_id}")
                self.audit.record_trusted_archive(
                    thread_id=thread_id,
                    plan_sha256=plan.plan_sha256,
                    manifest_sha256=evidence.manifest_sha256,
                )
