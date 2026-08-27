from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_session_manager.hashing import canonical_json_bytes, fingerprint
from codex_session_manager.models import (
    ActionPlan,
    CapabilityMatrix,
    PlanAction,
    PlanTarget,
    RiskLevel,
)
from codex_session_manager.plans import PlanStore
from codex_session_manager.protocol_profiles import AUDITED_PROTOCOL_PROFILES


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


def test_capability_matrix_requires_explicit_experimental_negotiation() -> None:
    profile = next(iter(AUDITED_PROTOCOL_PROFILES.values()))
    base = CapabilityMatrix(
        codex_version=profile.codex_version,
        codex_binary_sha256="a" * 64,
        schema_sha256=profile.schema_sha256,
        initialize_fingerprint="init",
        stable_methods=tuple(sorted(profile.stable_methods)),
        experimental_methods=tuple(sorted(profile.experimental_methods)),
        schema_complete=True,
    )
    base.require_write("thread/read")
    with pytest.raises(ValueError, match="explicitly negotiated"):
        base.require_write("thread/backgroundTerminals/list")
    enabled = base.model_copy(update={"experimental_api": True})
    enabled.require_write("thread/backgroundTerminals/list")


def test_capability_matrix_rejects_unknown_version_even_with_known_schema() -> None:
    profile = next(iter(AUDITED_PROTOCOL_PROFILES.values()))
    unknown = CapabilityMatrix(
        codex_version="0.149.1",
        codex_binary_sha256="a" * 64,
        schema_sha256=profile.schema_sha256,
        initialize_fingerprint="init",
        stable_methods=tuple(sorted(profile.stable_methods)),
        experimental_methods=tuple(sorted(profile.experimental_methods)),
        schema_complete=True,
    )

    assert not unknown.write_enabled
    with pytest.raises(ValueError, match="write capability disabled"):
        unknown.require_write("thread/archive")


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
