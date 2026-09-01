"""Cleanup planning and guarded execution."""

from __future__ import annotations

import csv
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from codex_session_manager.app_server import RequestError, RequestTimeout, SubprocessAppServer
from codex_session_manager.audit import AuditStore
from codex_session_manager.hashing import utc_now
from codex_session_manager.inventory import (
    InventoryFilter,
    InventoryService,
    _parent_ids,
    matches_filter,
    target_closure_ids,
)
from codex_session_manager.models import (
    SAFE_INACTIVE_STATUSES,
    ActionPlan,
    CapabilityMatrix,
    OperationName,
    PlanAction,
    PlanTarget,
    RiskLevel,
    ThreadHistoryMode,
    ThreadSnapshot,
    ThreadStatus,
)

DEFAULT_STALE_DAYS: Final[int] = 90
MAX_ROOTS: Final[int] = 100
PURGE_CONFIRMATION_PHRASE: Final[str] = "确认删除"
PURGE_EXECUTION_ENABLED: Final[bool] = False
PURGE_EXECUTION_BLOCKED_REASON: Final[str] = (
    "permanent deletion application is CLOSED_WITH_UPSTREAM_BLOCKER: "
    "the approved Codex App Server 0.142.1 can partially commit thread/delete "
    "against state migrated by a newer Codex; planning and review remain available"
)


@dataclass(frozen=True, slots=True)
class CleanupPolicy:
    stale_after: timedelta = timedelta(days=DEFAULT_STALE_DAYS)
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


def selected_root_block_reason(
    *,
    action: PlanAction,
    thread_id: str,
    snapshots: Mapping[str, ThreadSnapshot],
    capabilities: CapabilityMatrix,
    require_content_complete: bool = True,
) -> str | None:
    """Return the first shared task-closure eligibility failure."""

    root = snapshots.get(thread_id)
    if root is None:
        return f"selected conversation is no longer available: {thread_id}"
    closure_ids = (root.id, *root.spawned_descendant_ids)
    if len(set(closure_ids)) != len(closure_ids):
        return f"descendant closure is invalid for {thread_id}"
    missing = [member_id for member_id in closure_ids if member_id not in snapshots]
    if missing:
        return f"descendant closure is incomplete for {thread_id}: {', '.join(missing)}"
    if action not in {PlanAction.ARCHIVE, PlanAction.UNARCHIVE}:
        return f"cleanup action is not approved: {action.value}"

    try:
        capabilities.require_operation(OperationName.INVENTORY_COMMON)
    except ValueError as exc:
        return str(exc)
    operation = OperationName.ARCHIVE if action is PlanAction.ARCHIVE else OperationName.UNARCHIVE
    try:
        capabilities.require_operation(operation)
    except ValueError as exc:
        return str(exc)

    closure = tuple(snapshots[member_id] for member_id in closure_ids)
    for snapshot in closure:
        if snapshot.history_mode is ThreadHistoryMode.UNKNOWN:
            return f"history mode is unknown for {snapshot.id}"
        history_operation = (
            OperationName.HISTORY_PAGINATED
            if snapshot.history_mode is ThreadHistoryMode.PAGINATED
            else OperationName.HISTORY_LEGACY
        )
        try:
            capabilities.require_operation(history_operation)
        except ValueError as exc:
            return f"{snapshot.id}: {exc}"

    for snapshot in closure:
        if action is PlanAction.ARCHIVE and snapshot.archived:
            return f"conversation is already archived: {snapshot.id}"
        if action is PlanAction.UNARCHIVE and snapshot.id == root.id and not snapshot.archived:
            return f"conversation is not archived: {snapshot.id}"
        if snapshot.pinned:
            return f"conversation is pinned: {snapshot.id}"
        if snapshot.ephemeral:
            return f"ephemeral conversation cannot be managed: {snapshot.id}"
        if snapshot.status not in SAFE_INACTIVE_STATUSES:
            return f"conversation is active or in an unsafe state: {snapshot.id}"
        if not snapshot.mapping_complete:
            return f"conversation mapping is incomplete: {snapshot.id}"
        if require_content_complete and not snapshot.content_complete:
            return f"conversation content is incomplete: {snapshot.id}"
    return None


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
        roots = self._archive_roots(
            snapshots,
            cutoff=cutoff,
            criteria=criteria,
            require_content=True,
            maximum_roots=self.policy.maximum_roots,
        )
        roots = [
            root
            for root in roots
            if selected_root_block_reason(
                action=PlanAction.ARCHIVE,
                thread_id=root.id,
                snapshots=all_snapshots,
                capabilities=capabilities,
            )
            is None
        ]
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

    def archive_candidates(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        *,
        now: datetime | None = None,
        criteria: InventoryFilter | None = None,
    ) -> tuple[ThreadSnapshot, ...]:
        """Return safe, top-level archive suggestions without creating a write plan."""

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
        return tuple(roots)

    def archive_hydration_ids(
        self,
        summaries: tuple[ThreadSnapshot, ...],
        *,
        now: datetime | None = None,
        criteria: InventoryFilter | None = None,
        capabilities: CapabilityMatrix | None = None,
    ) -> tuple[str, ...]:
        """Select summary-only archive candidates before any content reads."""

        effective_now = (now or utc_now()).astimezone(UTC)
        all_snapshots = {snapshot.id: snapshot for snapshot in summaries}
        roots = self._archive_roots(
            summaries,
            cutoff=effective_now - self.policy.stale_after,
            criteria=criteria,
            require_content=False,
            maximum_roots=None,
        )
        if capabilities is not None:
            roots = [
                root
                for root in roots
                if selected_root_block_reason(
                    action=PlanAction.ARCHIVE,
                    thread_id=root.id,
                    snapshots=all_snapshots,
                    capabilities=capabilities,
                    require_content_complete=False,
                )
                is None
            ]
        roots = roots[: self.policy.maximum_roots]
        if not roots:
            return ()
        return target_closure_ids(summaries, tuple(root.id for root in roots))

    def manual_archive_candidates(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        *,
        criteria: InventoryFilter | None = None,
    ) -> tuple[ThreadSnapshot, ...]:
        """Return current safe roots that a human may explicitly add to review."""

        return tuple(
            self._manual_archive_roots(
                snapshots,
                criteria=criteria,
                require_content=True,
            )
        )

    def manual_archive_hydration_ids(
        self,
        summaries: tuple[ThreadSnapshot, ...],
        *,
        criteria: InventoryFilter | None = None,
    ) -> tuple[str, ...]:
        """Select bounded summary-only roots for explicit cleanup supplementation."""

        roots = self._manual_archive_roots(
            summaries,
            criteria=criteria,
            require_content=False,
        )
        if not roots:
            return ()
        return target_closure_ids(summaries, tuple(root.id for root in roots))

    def _manual_archive_roots(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        *,
        criteria: InventoryFilter | None,
        require_content: bool,
    ) -> list[ThreadSnapshot]:
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        candidates = [
            snapshot
            for snapshot in snapshots
            if not snapshot.archived
            and not snapshot.pinned
            and not snapshot.ephemeral
            and snapshot.mapping_complete
            and (snapshot.content_complete or not require_content)
            and snapshot.status in SAFE_INACTIVE_STATUSES
        ]
        candidate_ids = {snapshot.id for snapshot in candidates}
        roots = _non_overlapping_roots(
            [
                root
                for root in _top_level_candidates(candidates, all_snapshots)
                if {root.id, *root.spawned_descendant_ids} <= candidate_ids
                and (criteria is None or matches_filter(root, criteria))
            ]
        )
        return sorted(
            roots,
            key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC),
        )[: self.policy.maximum_roots]

    def _archive_roots(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        *,
        cutoff: datetime,
        criteria: InventoryFilter | None,
        require_content: bool,
        maximum_roots: int | None,
    ) -> list[ThreadSnapshot]:
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        candidates = [
            snapshot
            for snapshot in snapshots
            if not snapshot.archived
            and not snapshot.pinned
            and not snapshot.ephemeral
            and snapshot.mapping_complete
            and (snapshot.content_complete or not require_content)
            and snapshot.status in SAFE_INACTIVE_STATUSES
            and snapshot.updated_at is not None
            and snapshot.updated_at < cutoff
        ]
        candidate_ids = {snapshot.id for snapshot in candidates}
        roots = _non_overlapping_roots(
            [
                root
                for root in _top_level_candidates(candidates, all_snapshots)
                if {root.id, *root.spawned_descendant_ids} <= candidate_ids
                and (criteria is None or matches_filter(root, criteria))
            ]
        )
        roots = sorted(
            roots,
            key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC),
        )
        return roots if maximum_roots is None else roots[:maximum_roots]

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
            reason = selected_root_block_reason(
                action=PlanAction.ARCHIVE,
                thread_id=root.id,
                snapshots=all_snapshots,
                capabilities=capabilities,
            )
            if reason:
                raise ValueError(f"selected archive blocked: {reason}")
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
        selected = [
            root
            for root in selected
            if selected_root_block_reason(
                action=PlanAction.UNARCHIVE,
                thread_id=root.id,
                snapshots=all_snapshots,
                capabilities=capabilities,
            )
            is None
        ]
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

    def plan_selected_unarchive(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        selected_ids: tuple[str, ...],
    ) -> ActionPlan:
        """Plan an explicitly selected unarchive batch with full closure checks."""

        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self._explicit_roots(selected_ids, all_snapshots)
        targets: list[PlanTarget] = []
        for root in roots:
            reason = selected_root_block_reason(
                action=PlanAction.UNARCHIVE,
                thread_id=root.id,
                snapshots=all_snapshots,
                capabilities=capabilities,
            )
            if reason:
                raise ValueError(f"selected unarchive blocked: {reason}")
            targets.append(
                self._explicit_target(root, all_snapshots, "explicit human unarchive selection")
            )
        return ActionPlan.create(
            action=PlanAction.UNARCHIVE,
            capability_fingerprint=capabilities.fingerprint,
            targets=tuple(targets),
            prerequisites=(
                "all affected threads remain non-active and unpinned",
                "descendant closure and App Server capability fingerprint remain unchanged",
            ),
            options={"manual_selection": True},
        )

    def unarchive_hydration_ids(
        self,
        summaries: tuple[ThreadSnapshot, ...],
        *,
        criteria: InventoryFilter | None = None,
        capabilities: CapabilityMatrix | None = None,
    ) -> tuple[str, ...]:
        """Select summary-only unarchive roots before content hydration."""

        selected = [
            snapshot
            for snapshot in summaries
            if snapshot.archived and not snapshot.ephemeral and snapshot.mapping_complete
        ]
        all_snapshots = {snapshot.id: snapshot for snapshot in summaries}
        roots = _non_overlapping_roots(_top_level_candidates(selected, all_snapshots))
        if criteria is not None:
            roots = [snapshot for snapshot in roots if matches_filter(snapshot, criteria)]
        if capabilities is not None:
            roots = [
                root
                for root in roots
                if selected_root_block_reason(
                    action=PlanAction.UNARCHIVE,
                    thread_id=root.id,
                    snapshots=all_snapshots,
                    capabilities=capabilities,
                    require_content_complete=False,
                )
                is None
            ]
        roots = roots[: self.policy.maximum_roots]
        if not roots:
            return ()
        return target_closure_ids(summaries, tuple(root.id for root in roots))

    def plan_purge(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        capabilities: CapabilityMatrix,
        audit: AuditStore,
        *,
        now: datetime | None = None,
    ) -> ActionPlan:
        effective_now = (now or utc_now()).astimezone(UTC)
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self.purge_candidates(snapshots, audit, now=effective_now)[:1]
        targets = tuple(self._target(root, all_snapshots, effective_now) for root in roots)
        return ActionPlan.create(
            action=PlanAction.PURGE,
            capability_fingerprint=capabilities.fingerprint,
            targets=targets,
            prerequisites=(
                "CSM-trusted archive evidence exists for every affected snapshot",
                "verified encrypted backup covers every affected snapshot",
                "no other Codex process is running against the data root",
                "human supplies the exact plan id and permanent-deletion phrase",
            ),
            options={"manual_only": True, "trusted_archive_required": True},
        )

    def purge_candidates(
        self,
        snapshots: tuple[ThreadSnapshot, ...],
        audit: AuditStore,
        *,
        now: datetime | None = None,
    ) -> tuple[ThreadSnapshot, ...]:
        """Return roots satisfying every purge evidence gate without creating a plan."""

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
            if trusted is None:
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
        )
        return tuple(
            sorted(
                roots,
                key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC),
            )[: self.policy.maximum_roots]
        )

    def purge_hydration_ids(
        self,
        summaries: tuple[ThreadSnapshot, ...],
    ) -> tuple[str, ...]:
        """Select bounded archived roots whose content needs purge evidence checks."""

        all_snapshots = {snapshot.id: snapshot for snapshot in summaries}
        candidates = [
            snapshot
            for snapshot in summaries
            if snapshot.archived
            and not snapshot.pinned
            and not snapshot.ephemeral
            and snapshot.mapping_complete
            and snapshot.status in SAFE_INACTIVE_STATUSES
        ]
        candidate_ids = {snapshot.id for snapshot in candidates}
        roots = _non_overlapping_roots(
            [
                root
                for root in _top_level_candidates(candidates, all_snapshots)
                if {root.id, *root.spawned_descendant_ids} <= candidate_ids
            ]
        )
        roots = sorted(
            roots,
            key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC),
        )[: self.policy.maximum_roots]
        if not roots:
            return ()
        return target_closure_ids(summaries, tuple(root.id for root in roots))

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

        audit.verify_chain()
        all_snapshots = {snapshot.id: snapshot for snapshot in snapshots}
        roots = self._explicit_roots(selected_ids, all_snapshots)
        if len(roots) != 1:
            raise ValueError("permanent-deletion plans must contain exactly one root")
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
                if trusted is None:
                    raise ValueError(
                        f"selected permanent deletion requires CSM-trusted archive evidence: "
                        f"{snapshot.id}"
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
                "CSM-trusted archive evidence exists for every affected snapshot",
                "verified encrypted backup covers every affected snapshot",
                "no other Codex process is running against the data root",
                "human supplies the exact plan id and permanent-deletion phrase",
            ),
            options={
                "manual_only": True,
                "manual_selection": True,
                "trusted_archive_required": True,
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
        if os.name == "nt":
            ProcessGuard._assert_no_other_windows_codex_processes(controlled_pid)
            return
        completed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        processes: list[tuple[int, int, str]] = []
        for line in completed.stdout.splitlines():
            fields = line.strip().split(maxsplit=2)
            if len(fields) != 3:
                continue
            try:
                pid, parent_pid = int(fields[0]), int(fields[1])
            except ValueError:
                continue
            processes.append((pid, parent_pid, fields[2]))

        controlled_processes = {controlled_pid} if controlled_pid is not None else set()
        while descendants := {
            pid
            for pid, parent_pid, _command in processes
            if parent_pid in controlled_processes and pid not in controlled_processes
        }:
            controlled_processes.update(descendants)

        blockers: list[str] = []
        for pid, _parent_pid, command in processes:
            if pid in controlled_processes:
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

    @staticmethod
    def _assert_no_other_windows_codex_processes(controlled_pid: int | None) -> None:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        blockers: list[str] = []
        for row in csv.reader(completed.stdout.splitlines()):
            if len(row) < 2:
                continue
            image_name, pid_text = row[0], row[1]
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if controlled_pid is not None and pid == controlled_pid:
                continue
            if image_name.casefold() in {"codex.exe", "chatgpt.exe"}:
                blockers.append(f"{pid} {image_name}")
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
    ) -> tuple[str, ...]:
        plan.verify()
        if plan.action is PlanAction.PURGE and len(plan.targets) != 1:
            raise ValueError("permanent-deletion plans must contain exactly one root")
        if plan.action is PlanAction.PURGE and not PURGE_EXECUTION_ENABLED:
            raise RuntimeError(PURGE_EXECUTION_BLOCKED_REASON)
        self.audit.verify_chain()
        if plan.capability_fingerprint != self.capabilities.fingerprint:
            raise ValueError("App Server capability drift invalidated the plan")
        method = {
            PlanAction.ARCHIVE: "thread/archive",
            PlanAction.UNARCHIVE: "thread/unarchive",
            PlanAction.PURGE: "thread/delete",
        }.get(plan.action)
        if method is None:
            raise ValueError(f"CleanupExecutor cannot apply {plan.action.value}")
        self.capabilities.require_write(method)
        current = (
            self.inventory.list_for_targets(
                tuple(target.root_thread_id for target in plan.targets),
                include_active=True,
                include_archived=True,
            )
            if plan.action is PlanAction.PURGE
            else self.inventory.list(include_active=True, include_archived=True, include_turns=True)
        )
        current_by_id = self._verify_snapshot_drift(plan, current)
        if plan.action in {PlanAction.ARCHIVE, PlanAction.UNARCHIVE}:
            for target in plan.targets:
                reason = selected_root_block_reason(
                    action=plan.action,
                    thread_id=target.root_thread_id,
                    snapshots=current_by_id,
                    capabilities=self.capabilities,
                )
                if reason:
                    raise ValueError(f"cleanup plan is no longer eligible: {reason}")
        if plan.action in {PlanAction.ARCHIVE, PlanAction.PURGE}:
            self._verify_backup_gate(plan, current_by_id)
        if plan.action is PlanAction.PURGE:
            self.capabilities.require_write("thread/backgroundTerminals/list")
            self.capabilities.require_write("thread/loaded/list")
        affected = {
            thread_id for target in plan.targets for thread_id in target.affected_thread_ids
        }
        loaded = (
            set(self.client.loaded_thread_ids())
            if self.capabilities.supports("thread/loaded/list")
            else set()
        )
        if loaded & affected:
            raise RuntimeError(
                f"affected threads are loaded: {', '.join(sorted(loaded & affected))}"
            )
        if plan.action is PlanAction.PURGE:
            if confirmation != PURGE_CONFIRMATION_PHRASE:
                raise ValueError("missing permanent-deletion confirmation phrase")
            self._verify_purge_gate(plan, plan.targets, current_by_id)
            background_processes = {
                thread_id: self._purge_background_terminals(current_by_id[thread_id])
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

        self.audit.begin_operation(plan_sha256=plan.plan_sha256, action=plan.action.value)
        completed: list[str] = []
        ambiguous_write_errors: list[RequestError | RequestTimeout] = []
        try:
            if plan.action is PlanAction.UNARCHIVE:
                for thread_id in sorted(affected):
                    self.audit.invalidate_trusted_archive(
                        thread_id=thread_id, plan_sha256=plan.plan_sha256
                    )
            for target in plan.targets:
                if plan.action is PlanAction.PURGE:
                    fresh = self.inventory.list_for_targets(
                        (target.root_thread_id,),
                        include_active=True,
                        include_archived=True,
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
                        thread_id: self._purge_background_terminals(fresh_by_id[thread_id])
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
                thread_ids = (
                    tuple(reversed(target.affected_thread_ids))
                    if plan.action is PlanAction.ARCHIVE
                    else target.affected_thread_ids
                    if plan.action is PlanAction.UNARCHIVE
                    else (target.root_thread_id,)
                )
                for thread_id in thread_ids:
                    if (
                        plan.action is PlanAction.UNARCHIVE
                        and not current_by_id[thread_id].archived
                    ):
                        continue
                    write_error = self._apply_root(plan, thread_id)
                    if write_error is not None:
                        ambiguous_write_errors.append(write_error)
                completed.append(target.root_thread_id)
            try:
                self._verify_result(plan, affected)
            except RuntimeError as exc:
                if ambiguous_write_errors:
                    reported = "; ".join(str(error) for error in ambiguous_write_errors)
                    raise RuntimeError(f"{exc}; App Server reported: {reported}") from exc
                raise
            if plan.action is PlanAction.ARCHIVE:
                self._record_archives(plan, current_by_id)
            self.audit.finish_operation(plan_sha256=plan.plan_sha256, status="succeeded")
            details: dict[str, object] = {"root_count": len(plan.targets)}
            if ambiguous_write_errors:
                details["reconciled_app_server_errors"] = [
                    str(error) for error in ambiguous_write_errors
                ]
            self.audit.append(
                event_type=f"{plan.action.value}.apply",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(sorted(affected)),
                details=details,
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

    def _purge_background_terminals(
        self, snapshot: ThreadSnapshot
    ) -> tuple[dict[str, object], ...]:
        """Normalize the App Server's archived/notLoaded not-found sentinel."""

        try:
            return self.client.background_terminals(snapshot.id)
        except RequestError as exc:
            if (
                snapshot.archived
                and snapshot.status is ThreadStatus.NOT_LOADED
                and exc.method == "thread/backgroundTerminals/list"
                and exc.code == -32600
                and exc.message == f"thread not found: {snapshot.id}"
            ):
                return ()
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

    def _apply_root(self, plan: ActionPlan, thread_id: str) -> RequestError | RequestTimeout | None:
        try:
            if plan.action is PlanAction.ARCHIVE:
                self.client.archive_thread(thread_id)
            elif plan.action is PlanAction.UNARCHIVE:
                self.client.unarchive_thread(thread_id)
            elif plan.action is PlanAction.PURGE:
                self.client.delete_thread(thread_id)
            else:
                raise ValueError(f"CleanupExecutor cannot apply {plan.action.value}")
        except (RequestError, RequestTimeout) as exc:
            # Never retry.  The postcondition query in _verify_result determines
            # whether the operation committed; an unresolved state stays failed.
            if not exc.may_have_committed:
                raise
            return exc
        return None

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
            elif not snapshot.archived and (
                plan.action is PlanAction.PURGE
                or (plan.action is PlanAction.UNARCHIVE and thread_id == target.root_thread_id)
            ):
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
        if (
            plan.options.get("manual_only") is not True
            or plan.options.get("trusted_archive_required") is not True
        ):
            raise ValueError("purge plan lacks the manual trusted-archive gate")
        for target in targets:
            for thread_id in target.affected_thread_ids:
                snapshot = current_by_id.get(thread_id)
                if snapshot is None or not snapshot.archived:
                    raise ValueError(f"thread is no longer archived: {thread_id}")
                trusted = self.audit.trusted_archive(thread_id)
                if trusted is None:
                    raise ValueError(f"trusted archive evidence is missing: {thread_id}")
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
            raise ValueError(f"CleanupExecutor cannot verify {plan.action.value}")
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
