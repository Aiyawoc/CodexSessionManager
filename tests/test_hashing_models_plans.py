from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_session_manager.hashing import canonical_json_bytes, fingerprint
from codex_session_manager.models import (
    ActionPlan,
    ContractIssue,
    OperationCapability,
    OperationName,
    PlanAction,
    PlanTarget,
    RiskLevel,
    ThreadHistoryMode,
)
from codex_session_manager.plans import PlanStore


def _rebuild(model, **updates):
    values = model.model_dump(mode="python")
    values.update(updates)
    return type(model)(**values)


def test_canonical_hash_is_order_independent() -> None:
    left = {"b": [2, 1], "a": {"z": True, "x": None}}
    right = {"a": {"x": None, "z": True}, "b": [2, 1]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert fingerprint(left) == fingerprint(right)


def test_action_plan_tamper_and_immutable_store(app_paths, capabilities) -> None:
    target = PlanTarget(
        root_thread_id="root",
        affected_thread_ids=("root",),
        snapshot_fingerprints={"root": "f" * 64},
        risk=RiskLevel.LOW,
    )
    plan = ActionPlan.create(
        action=PlanAction.ARCHIVE,
        capability_fingerprint=capabilities.fingerprint,
        targets=(target,),
    )
    plan.verify()
    store = PlanStore(app_paths)
    path = store.save(plan)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert store.save(plan) == path

    tampered = plan.model_copy(update={"options": {"changed": True}})
    with pytest.raises(ValueError, match="SHA-256"):
        tampered.verify()
    path.write_text(json.dumps(tampered.model_dump(mode="json")), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        store.load_action(path)


def test_capability_matrix_queries_each_operation(operation_capabilities, capabilities) -> None:
    assert tuple(capabilities.operation(name).operation for name in OperationName) == tuple(
        OperationName
    )
    assert all(capabilities.supports_operation(name) for name in OperationName)
    assert all(
        set(capability.required_methods)
        <= {evidence.method for evidence in capability.method_evidence}
        for capability in operation_capabilities
    )


def test_operation_capability_validates_availability_evidence(operation_capabilities) -> None:
    available = operation_capabilities[0]
    assert available.runtime_contract_fingerprint is not None
    assert not available.issues

    with pytest.raises(ValueError, match="runtime_contract_fingerprint"):
        _rebuild(available, runtime_contract_fingerprint=None)

    with pytest.raises(ValueError, match="at least one issue"):
        OperationCapability(
            operation=OperationName.ARCHIVE,
            contract_id="archive.v1",
            available=False,
            contract_rule_fingerprint="rule",
            runtime_contract_fingerprint="runtime",
        )

    blocked = OperationCapability(
        operation=OperationName.ARCHIVE,
        contract_id="archive.v1",
        available=False,
        contract_rule_fingerprint="rule",
        issues=(ContractIssue(code="missing_method", subject="thread/archive"),),
    )
    assert not blocked.available


def test_capability_matrix_requires_exactly_one_of_each_operation(
    operation_capabilities, capabilities
) -> None:
    with pytest.raises(ValueError, match="exactly once"):
        _rebuild(
            capabilities,
            operation_capabilities=operation_capabilities[:-1],
        )
    with pytest.raises(ValueError, match="exactly once"):
        _rebuild(
            capabilities,
            operation_capabilities=(*operation_capabilities[:-1], operation_capabilities[0]),
        )


def test_capability_fingerprint_tracks_runtime_evidence_not_archive_support(
    capabilities,
) -> None:
    assert capabilities.supports_operation(OperationName.ARCHIVE)
    for field in ("codex_version", "codex_binary_sha256", "schema_sha256"):
        changed = capabilities.model_copy(update={field: f"changed-{field}"})
        assert changed.supports_operation(OperationName.ARCHIVE)
        assert changed.fingerprint != capabilities.fingerprint


def test_require_write_allows_only_approved_archive_operations(capabilities) -> None:
    capabilities.require_write("thread/archive")
    capabilities.require_write("thread/unarchive")
    for method in (
        "thread/start",
        "thread/fork",
        "thread/rollback",
        "thread/inject_items",
        "thread/name/set",
    ):
        with pytest.raises(
            ValueError,
            match=f"no approved operation contract for App Server write: {method}",
        ):
            capabilities.require_write(method)


def test_unavailable_operation_is_rejected(operation_capabilities, capabilities) -> None:
    blocked = operation_capabilities[3].model_copy(
        update={
            "available": False,
            "runtime_contract_fingerprint": None,
            "issues": (ContractIssue(code="missing_method", subject="thread/archive"),),
        }
    )
    matrix = _rebuild(
        capabilities,
        operation_capabilities=(*operation_capabilities[:3], blocked, *operation_capabilities[4:]),
    )
    assert not matrix.supports_operation(OperationName.ARCHIVE)
    with pytest.raises(ValueError, match="archive"):
        matrix.require_write("thread/archive")


def test_history_mode_is_bound_to_management_and_backup_fingerprints(snapshot_factory) -> None:
    legacy = snapshot_factory(history_mode=ThreadHistoryMode.LEGACY)
    paginated = legacy.model_copy(update={"history_mode": ThreadHistoryMode.PAGINATED})
    assert legacy.management_fingerprint != paginated.management_fingerprint
    assert legacy.backup_fingerprint != paginated.backup_fingerprint


def test_operation_capability_requires_evidence_for_available_methods(
    operation_capabilities,
) -> None:
    archive = operation_capabilities[3]
    with pytest.raises(ValueError, match="method_evidence"):
        _rebuild(archive, method_evidence=())


def test_plan_store_rejects_changed_bytes_for_same_identity(app_paths, capabilities) -> None:
    target = PlanTarget(
        root_thread_id="root",
        affected_thread_ids=("root",),
        snapshot_fingerprints={"root": "f" * 64},
    )
    plan = ActionPlan.create(
        action=PlanAction.UNARCHIVE,
        capability_fingerprint=capabilities.fingerprint,
        targets=(target,),
    )
    store = PlanStore(app_paths)
    path = store.save(plan)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="different bytes"):
        store.save(plan)


def test_plan_file_name_is_bounded_to_plan_identity(app_paths, capabilities) -> None:
    target = PlanTarget(
        root_thread_id="root",
        affected_thread_ids=("root",),
        snapshot_fingerprints={"root": "f" * 64},
    )
    plan = ActionPlan.create(
        action=PlanAction.ARCHIVE,
        capability_fingerprint=capabilities.fingerprint,
        targets=(target,),
    )
    path: Path = PlanStore(app_paths).path_for(plan)
    assert path.parent == app_paths.plans_dir
    assert path.name == f"action-{plan.plan_id}.json"


def test_action_plan_rejects_overlapping_target_closures(capabilities) -> None:
    left = PlanTarget(
        root_thread_id="left",
        affected_thread_ids=("left", "shared"),
        snapshot_fingerprints={"left": "a" * 64, "shared": "b" * 64},
    )
    right = PlanTarget(
        root_thread_id="right",
        affected_thread_ids=("right", "shared"),
        snapshot_fingerprints={"right": "c" * 64, "shared": "b" * 64},
    )
    plan = ActionPlan.create(
        action=PlanAction.ARCHIVE,
        capability_fingerprint=capabilities.fingerprint,
        targets=(left, right),
    )
    with pytest.raises(ValueError, match="closures overlap"):
        plan.verify()
