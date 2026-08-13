from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codex_session_manager.acceptance import (
    AcceptanceScope,
    AcceptanceStage,
    AcceptanceStageName,
    AcceptanceStageResult,
    create_acceptance_report,
)
from codex_session_manager.models import CapabilityMatrix
from codex_session_manager.protocol_profiles import AUDITED_PROTOCOL_PROFILES
from codex_session_manager.schema_audit import (
    SchemaAuditConclusion,
    SchemaDifferenceKind,
    build_schema_audit_report,
)


def _profile_capabilities(
    *,
    schema_sha256: str | None = None,
    stable_methods: tuple[str, ...] | None = None,
    experimental_methods: tuple[str, ...] | None = None,
    fork_supports_last_turn_id: bool = False,
    schema_complete: bool = True,
    read_only_reason: str | None = None,
    binary_sha256: str | None = "a" * 64,
) -> CapabilityMatrix:
    profile = next(iter(AUDITED_PROTOCOL_PROFILES.values()))
    digest = profile.schema_sha256 if schema_sha256 is None else schema_sha256
    return CapabilityMatrix(
        codex_version=profile.codex_version,
        codex_binary_path="/private/account/bin/codex",
        codex_binary_sha256=binary_sha256,
        initialize_fingerprint="init",
        schema_sha256=digest,
        stable_methods=(
            tuple(sorted(profile.stable_methods)) if stable_methods is None else stable_methods
        ),
        experimental_methods=(
            tuple(sorted(profile.experimental_methods))
            if experimental_methods is None
            else experimental_methods
        ),
        fork_supports_last_turn_id=fork_supports_last_turn_id,
        schema_complete=schema_complete,
        read_only_reason=read_only_reason,
    )


def test_exact_schema_audit_is_sealed_and_omits_private_paths() -> None:
    report = build_schema_audit_report(
        _profile_capabilities(),
        generated_at=datetime(2026, 8, 13, tzinfo=UTC),
        platform_name="darwin",
        architecture="arm64",
    )

    report.verify()
    assert report.conclusion is SchemaAuditConclusion.TRUSTED_WRITE
    assert report.write_enabled
    assert report.exact_profile_match
    assert report.differences == ()
    encoded = report.model_dump_json()
    assert "/private/account" not in encoded
    assert '"platform":"darwin"' in encoded
    assert '"architecture":"arm64"' in encoded


def test_schema_audit_classifies_added_removed_stability_and_field_changes() -> None:
    profile = next(iter(AUDITED_PROTOCOL_PROFILES.values()))
    stable = set(profile.stable_methods)
    experimental = set(profile.experimental_methods)
    stable.remove("thread/read")
    experimental.add("thread/read")
    stable.remove("thread/archive")
    stable.add("thread/future")
    report = build_schema_audit_report(
        _profile_capabilities(
            schema_sha256="c" * 64,
            stable_methods=tuple(sorted(stable)),
            experimental_methods=tuple(sorted(experimental)),
            fork_supports_last_turn_id=True,
            read_only_reason="unknown schema",
        )
    )

    kinds = {difference.kind for difference in report.differences}
    assert report.conclusion is SchemaAuditConclusion.INCOMPLETE_SCHEMA_READ_ONLY
    assert not report.write_enabled
    assert SchemaDifferenceKind.ADDED_METHOD in kinds
    assert SchemaDifferenceKind.REMOVED_METHOD in kinds
    assert SchemaDifferenceKind.METHOD_STABILITY_CHANGED in kinds
    assert SchemaDifferenceKind.CRITICAL_FIELD_CHANGED in kinds


def test_same_method_inventory_with_unknown_hash_is_still_an_unknown_profile() -> None:
    report = build_schema_audit_report(
        _profile_capabilities(
            schema_sha256="d" * 64,
            read_only_reason="schema command failed at /private/account/bin/codex",
        )
    )

    assert report.conclusion is SchemaAuditConclusion.UNKNOWN_SCHEMA_READ_ONLY
    assert not report.exact_profile_match
    assert [difference.kind for difference in report.differences] == [
        SchemaDifferenceKind.UNKNOWN_PROFILE
    ]
    assert report.differences[0].actual == "d" * 64
    assert "/private/account" not in report.model_dump_json()


def test_unavailable_schema_audit_stays_read_only() -> None:
    report = build_schema_audit_report(
        _profile_capabilities(
            schema_sha256="",
            stable_methods=(),
            experimental_methods=(),
            schema_complete=False,
            read_only_reason="generation failed",
            binary_sha256=None,
        )
    )

    assert report.conclusion is SchemaAuditConclusion.UNAVAILABLE_READ_ONLY
    assert not report.write_enabled
    assert report.missing_required_methods


def test_acceptance_report_hashes_ids_and_cannot_claim_production() -> None:
    schema_report = build_schema_audit_report(_profile_capabilities())
    raw_thread_id = "019ff-secret-thread-id"
    report = create_acceptance_report(
        scope=AcceptanceScope.MACOS_REAL_ACCOUNT,
        schema_report=schema_report,
        stages=(
            AcceptanceStage(
                name=AcceptanceStageName.DOCTOR,
                result=AcceptanceStageResult.PASSED,
            ),
            AcceptanceStage(
                name=AcceptanceStageName.DERIVED_ARCHIVED,
                result=AcceptanceStageResult.NOT_RUN,
            ),
        ),
        thread_ids=(raw_thread_id, raw_thread_id),
        plan_sha256s=("1" * 64,),
        backup_manifest_sha256s=("2" * 64,),
        audit_sha256="3" * 64,
    )

    report.verify()
    encoded = report.model_dump_json()
    assert raw_thread_id not in encoded
    assert len(report.task_id_hashes) == 1
    assert report.production_ready is False
    assert "not-production-acceptance" in report.limitations


def test_acceptance_report_rejects_duplicate_stages() -> None:
    schema_report = build_schema_audit_report(_profile_capabilities())
    duplicate = AcceptanceStage(
        name=AcceptanceStageName.DOCTOR,
        result=AcceptanceStageResult.PASSED,
    )
    with pytest.raises(ValueError, match="duplicates"):
        create_acceptance_report(
            scope=AcceptanceScope.MACOS_REAL_ACCOUNT,
            schema_report=schema_report,
            stages=(duplicate, duplicate),
        )

    with pytest.raises(ValueError, match="at least one stage"):
        create_acceptance_report(
            scope=AcceptanceScope.MACOS_REAL_ACCOUNT,
            schema_report=schema_report,
            stages=(),
        )
