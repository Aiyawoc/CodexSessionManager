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
from codex_session_manager.models import (
    CapabilityMatrix,
    ContractIssue,
    OperationCapability,
    OperationName,
)
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
    digest = "b" * 64 if schema_sha256 is None else schema_sha256
    operation_capabilities = tuple(
        OperationCapability(
            operation=operation,
            contract_id=f"{operation.value}.v1",
            available=False,
            contract_rule_fingerprint="rule",
            issues=(
                ContractIssue(
                    code="test_only",
                    subject=operation.value,
                ),
            ),
        )
        for operation in OperationName
    )
    return CapabilityMatrix(
        codex_version="fixture-codex",
        codex_binary_path="/private/account/bin/codex",
        codex_binary_sha256=binary_sha256,
        initialize_fingerprint="init",
        schema_sha256=digest,
        stable_methods=(
            (
                "initialize",
                "thread/list",
                "thread/read",
                "thread/loaded/list",
                "thread/archive",
            )
            if stable_methods is None
            else stable_methods
        ),
        experimental_methods=() if experimental_methods is None else experimental_methods,
        fork_supports_last_turn_id=fork_supports_last_turn_id,
        schema_complete=schema_complete,
        operation_capabilities=operation_capabilities,
    )


def test_schema_audit_is_sealed_and_omits_private_paths() -> None:
    report = build_schema_audit_report(
        _profile_capabilities(),
        generated_at=datetime(2026, 8, 13, tzinfo=UTC),
        platform_name="darwin",
        architecture="arm64",
    )

    report.verify()
    assert report.conclusion is SchemaAuditConclusion.UNKNOWN_SCHEMA_READ_ONLY
    assert not report.write_enabled
    assert not report.exact_profile_match
    assert report.differences
    encoded = report.model_dump_json()
    assert "/private/account" not in encoded
    assert '"platform":"darwin"' in encoded
    assert '"architecture":"arm64"' in encoded


def test_schema_audit_classifies_added_removed_stability_and_field_changes() -> None:
    stable = {
        "initialize",
        "thread/list",
        "thread/read",
        "thread/loaded/list",
        "thread/archive",
    }
    experimental: set[str] = set()
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
    assert kinds == {SchemaDifferenceKind.UNKNOWN_PROFILE}


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
