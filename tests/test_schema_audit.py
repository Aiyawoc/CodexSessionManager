from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
    ContractMethodEvidence,
    OperationCapability,
    OperationName,
)
from codex_session_manager.schema_audit import (
    SchemaAuditConclusion,
    SchemaAuditReport,
    build_schema_audit_report,
)


def _capability(operation: OperationName, *, available: bool = True) -> OperationCapability:
    methods = {
        OperationName.INVENTORY_COMMON: (
            "initialize",
            "thread/list",
            "thread/read",
            "thread/loaded/list",
        ),
        OperationName.HISTORY_LEGACY: ("thread/read",),
        OperationName.HISTORY_PAGINATED: ("thread/turns/list",),
        OperationName.ARCHIVE: ("thread/archive",),
        OperationName.UNARCHIVE: ("thread/unarchive",),
    }[operation]
    if available:
        return OperationCapability(
            operation=operation,
            contract_id=f"{operation.value}.v1",
            available=True,
            contract_rule_fingerprint=f"rule-{operation.value}",
            runtime_contract_fingerprint=f"runtime-{operation.value}",
            required_methods=methods,
            method_evidence=tuple(
                ContractMethodEvidence(method=method, stability="stable", negotiated=False)
                for method in methods
            ),
        )
    return OperationCapability(
        operation=operation,
        contract_id=f"{operation.value}.v1",
        available=False,
        contract_rule_fingerprint=f"rule-{operation.value}",
        required_methods=methods,
        issues=(
            ContractIssue(
                code="missing_method",
                subject=methods[0],
                expected="stable",
                actual="missing",
            ),
        ),
    )


def _capabilities(
    *,
    codex_version: str = "fixture-codex",
    schema_sha256: str | None = "b" * 64,
    available: frozenset[OperationName] | None = None,
    probe_error: str | None = None,
) -> CapabilityMatrix:
    available = available if available is not None else frozenset(OperationName)
    return CapabilityMatrix(
        codex_version=codex_version,
        codex_binary_path="/private/account/bin/codex",
        codex_binary_sha256="a" * 64,
        initialize_fingerprint="init",
        schema_sha256=schema_sha256,
        stable_methods=("initialize", "thread/list", "thread/read", "thread/loaded/list"),
        experimental_methods=("thread/turns/list",),
        schema_complete=probe_error is None,
        operation_capabilities=tuple(
            _capability(operation, available=operation in available) for operation in OperationName
        ),
        probe_error=probe_error,
    )


def test_schema_audit_is_sealed_v2_and_serializes_five_operations() -> None:
    report = build_schema_audit_report(
        _capabilities(),
        generated_at=datetime(2026, 8, 13, tzinfo=UTC),
        platform_name="darwin",
        architecture="arm64",
    )

    report.verify()
    assert report.schema_version == 2
    assert report.conclusion is SchemaAuditConclusion.COMPATIBLE
    assert {capability.operation for capability in report.operation_capabilities} == set(
        OperationName
    )
    encoded = report.model_dump_json()
    assert "/private/account" not in encoded
    assert '"platform":"darwin"' in encoded
    assert '"architecture":"arm64"' in encoded
    for field in (
        "compared_profile_version",
        "compared_profile_schema_sha256",
        "exact_profile_match",
        "write_enabled",
    ):
        assert field not in encoded


def test_version_and_full_schema_hash_changes_do_not_change_contract_result() -> None:
    first = build_schema_audit_report(_capabilities())
    second = build_schema_audit_report(
        _capabilities(codex_version="new-codex", schema_sha256="c" * 64)
    )

    assert first.conclusion is SchemaAuditConclusion.COMPATIBLE
    assert second.conclusion is SchemaAuditConclusion.COMPATIBLE
    assert first.operation_capabilities == second.operation_capabilities


def test_only_paginated_contract_failure_is_partial_with_structured_issue() -> None:
    report = build_schema_audit_report(
        _capabilities(available=frozenset(OperationName) - {OperationName.HISTORY_PAGINATED})
    )

    assert report.conclusion is SchemaAuditConclusion.PARTIAL
    paginated = next(
        capability
        for capability in report.operation_capabilities
        if capability.operation is OperationName.HISTORY_PAGINATED
    )
    assert not paginated.available
    assert paginated.issues[0].code == "missing_method"
    assert "unknown version" not in report.model_dump_json()
    assert "unknown schema" not in report.model_dump_json()


def test_schema_generation_failure_is_unavailable_and_report_remains_verifiable() -> None:
    report = build_schema_audit_report(
        _capabilities(
            schema_sha256=None,
            available=frozenset(),
            probe_error="schema generation failed",
        )
    )

    assert report.conclusion is SchemaAuditConclusion.UNAVAILABLE
    assert report.probe_error == "schema generation failed"
    report.verify()


@pytest.mark.parametrize(
    ("private_path", "private_fragments"),
    (
        (
            str(Path.home() / "Private Folder" / "codex"),
            ("Private Folder", "codex"),
        ),
        (
            f'"{Path.home() / "Private Folder" / "codex"}"',
            ("Private Folder", "codex"),
        ),
        (
            "/private-test-user/Private Folder/codex",
            ("private-test-user", "Private Folder", "codex"),
        ),
        (
            '"/private-test-user/Private Folder/codex"',
            ("private-test-user", "Private Folder", "codex"),
        ),
        (
            r"C:\Users\private-test-user\Private Folder\codex.exe",
            ("private-test-user", "Private Folder", "codex.exe"),
        ),
        (
            r'"C:\Users\private-test-user\Private Folder\codex.exe"',
            ("private-test-user", "Private Folder", "codex.exe"),
        ),
        (
            r"C:/Users/private-test-user/Private Folder/codex.exe",
            ("private-test-user", "Private Folder", "codex.exe"),
        ),
        (
            r'"C:/Users/private-test-user/Private Folder/codex.exe"',
            ("private-test-user", "Private Folder", "codex.exe"),
        ),
    ),
)
def test_probe_error_redacts_full_private_paths_with_spaces(
    private_path: str, private_fragments: tuple[str, ...]
) -> None:
    prefix = "schema generation failed while opening "
    error = prefix + private_path
    report = build_schema_audit_report(_capabilities(available=frozenset(), probe_error=error))

    assert report.probe_error is not None
    assert report.probe_error.startswith(prefix)
    for private_fragment in private_fragments:
        assert private_fragment not in report.probe_error
    report.verify()


def test_probe_error_redacts_home_user_and_private_executable_path() -> None:
    error = (
        "schema generation failed for /Users/private-test-user/private/codex/bin/codex "
        "at /private/account/bin/codex"
    )
    report = build_schema_audit_report(_capabilities(available=frozenset(), probe_error=error))

    assert report.probe_error is not None
    assert "/Users/private-test-user" not in report.probe_error
    assert "/private/account" not in report.probe_error
    assert "schema generation failed" in report.probe_error
    report.verify()


def test_schema_audit_rejects_legacy_authorization_fields() -> None:
    report = build_schema_audit_report(_capabilities())
    payload = report.model_dump(mode="json")
    payload["write_enabled"] = True
    with pytest.raises(ValueError, match="extra_forbidden"):
        SchemaAuditReport.model_validate(payload)


def test_acceptance_report_hashes_ids_and_cannot_claim_production() -> None:
    schema_report = build_schema_audit_report(_capabilities())
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
    schema_report = build_schema_audit_report(_capabilities())
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
