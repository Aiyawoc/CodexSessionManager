"""Normalized, read-only evidence for App Server schema review."""

from __future__ import annotations

import platform
import sys
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from codex_session_manager.app_server import BASELINE_METHODS, probe_capabilities
from codex_session_manager.config import private_atomic_create
from codex_session_manager.hashing import canonical_json_bytes, sealed_fingerprint, utc_now
from codex_session_manager.models import CapabilityMatrix, FrozenModel
from codex_session_manager.protocol_profiles import (
    AUDITED_PROTOCOL_PROFILES,
    ProtocolProfile,
    nearest_profile,
)
from codex_session_manager.version import __version__


class SchemaAuditConclusion(StrEnum):
    TRUSTED_WRITE = "trusted_write"
    UNKNOWN_SCHEMA_READ_ONLY = "unknown_schema_read_only"
    INCOMPLETE_SCHEMA_READ_ONLY = "incomplete_schema_read_only"
    UNAVAILABLE_READ_ONLY = "unavailable_read_only"


class SchemaDifferenceKind(StrEnum):
    ADDED_METHOD = "added_method"
    REMOVED_METHOD = "removed_method"
    METHOD_STABILITY_CHANGED = "method_stability_changed"
    CRITICAL_FIELD_CHANGED = "critical_field_changed"
    UNKNOWN_PROFILE = "unknown_profile"


class SchemaDifference(FrozenModel):
    kind: SchemaDifferenceKind
    subject: str
    expected: str | None = None
    actual: str | None = None


class SchemaAuditReport(FrozenModel):
    """Portable evidence that intentionally excludes executable/private paths."""

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    tool_version: str
    platform: str
    architecture: str
    codex_version: str | None = None
    codex_binary_sha256: str | None = None
    schema_sha256: str | None = None
    capability_fingerprint: str
    stable_methods: tuple[str, ...] = ()
    experimental_methods: tuple[str, ...] = ()
    required_methods: tuple[str, ...] = ()
    missing_required_methods: tuple[str, ...] = ()
    critical_fields: dict[str, bool] = Field(default_factory=dict)
    compared_profile_version: str | None = None
    compared_profile_schema_sha256: str | None = None
    exact_profile_match: bool = False
    differences: tuple[SchemaDifference, ...] = ()
    conclusion: SchemaAuditConclusion
    write_enabled: bool = False
    read_only_reason: str | None = None
    report_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(update={"report_sha256": sealed_fingerprint(self, "report_sha256")})

    def verify(self) -> None:
        if self.report_sha256 != sealed_fingerprint(self, "report_sha256"):
            raise ValueError("SchemaAuditReport SHA-256 mismatch")

    @model_validator(mode="after")
    def validate_conclusion(self) -> Self:
        if self.conclusion is SchemaAuditConclusion.TRUSTED_WRITE:
            if not self.write_enabled or not self.exact_profile_match or self.differences:
                raise ValueError("trusted schema report must exactly match an approved profile")
        elif self.write_enabled:
            raise ValueError("non-trusted schema report cannot claim write capability")
        return self


def _critical_fields(capabilities: CapabilityMatrix) -> dict[str, bool]:
    return {"ThreadForkParams.lastTurnId": capabilities.fork_supports_last_turn_id}


def _method_differences(
    capabilities: CapabilityMatrix,
    profile: ProtocolProfile | None,
) -> tuple[SchemaDifference, ...]:
    if profile is None:
        return (
            SchemaDifference(
                kind=SchemaDifferenceKind.UNKNOWN_PROFILE,
                subject="App Server schema",
                actual=capabilities.schema_sha256,
            ),
        )
    actual_stable = set(capabilities.stable_methods)
    actual_experimental = set(capabilities.experimental_methods)
    expected_stable = set(profile.stable_methods)
    expected_experimental = set(profile.experimental_methods)
    changed_to_experimental = expected_stable & actual_experimental
    changed_to_stable = expected_experimental & actual_stable
    changed = changed_to_experimental | changed_to_stable
    expected_all = expected_stable | expected_experimental
    actual_all = actual_stable | actual_experimental
    differences: list[SchemaDifference] = []
    differences.extend(
        SchemaDifference(
            kind=SchemaDifferenceKind.ADDED_METHOD,
            subject=method,
            expected="absent",
            actual=("stable" if method in actual_stable else "experimental"),
        )
        for method in sorted(actual_all - expected_all)
    )
    differences.extend(
        SchemaDifference(
            kind=SchemaDifferenceKind.REMOVED_METHOD,
            subject=method,
            expected=("stable" if method in expected_stable else "experimental"),
            actual="absent",
        )
        for method in sorted((expected_all - actual_all) - changed)
    )
    differences.extend(
        SchemaDifference(
            kind=SchemaDifferenceKind.METHOD_STABILITY_CHANGED,
            subject=method,
            expected="stable",
            actual="experimental",
        )
        for method in sorted(changed_to_experimental)
    )
    differences.extend(
        SchemaDifference(
            kind=SchemaDifferenceKind.METHOD_STABILITY_CHANGED,
            subject=method,
            expected="experimental",
            actual="stable",
        )
        for method in sorted(changed_to_stable)
    )
    actual_fields = _critical_fields(capabilities)
    differences.extend(
        SchemaDifference(
            kind=SchemaDifferenceKind.CRITICAL_FIELD_CHANGED,
            subject=field,
            expected=str(expected).lower(),
            actual=str(actual_fields.get(field, False)).lower(),
        )
        for field, expected in sorted(profile.critical_fields.items())
        if actual_fields.get(field, False) is not expected
    )
    return tuple(differences)


def build_schema_audit_report(
    capabilities: CapabilityMatrix,
    *,
    generated_at: AwareDatetime | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> SchemaAuditReport:
    """Classify an already-probed capability matrix without any writes."""

    exact_profile = (
        AUDITED_PROTOCOL_PROFILES.get((capabilities.codex_version, capabilities.schema_sha256))
        if capabilities.codex_version is not None and capabilities.schema_sha256 is not None
        else None
    )
    comparison = exact_profile or nearest_profile(capabilities.codex_version)
    method_differences = _method_differences(capabilities, comparison)
    if exact_profile is None and comparison is not None:
        profile_difference = SchemaDifference(
            kind=SchemaDifferenceKind.UNKNOWN_PROFILE,
            subject="App Server schema",
            expected=comparison.schema_sha256,
            actual=capabilities.schema_sha256,
        )
        differences = (profile_difference, *method_differences)
    else:
        differences = method_differences
    missing = tuple(sorted(BASELINE_METHODS - set(capabilities.stable_methods)))
    if capabilities.schema_sha256 is None or capabilities.codex_binary_sha256 is None:
        conclusion = SchemaAuditConclusion.UNAVAILABLE_READ_ONLY
    elif missing or not capabilities.schema_complete:
        conclusion = SchemaAuditConclusion.INCOMPLETE_SCHEMA_READ_ONLY
    elif exact_profile is not None and not differences and capabilities.write_enabled:
        conclusion = SchemaAuditConclusion.TRUSTED_WRITE
    else:
        conclusion = SchemaAuditConclusion.UNKNOWN_SCHEMA_READ_ONLY
    write_enabled = conclusion is SchemaAuditConclusion.TRUSTED_WRITE
    if write_enabled:
        read_only_reason = None
    elif conclusion is SchemaAuditConclusion.UNAVAILABLE_READ_ONLY:
        read_only_reason = "unable to establish an exact local App Server schema"
    elif conclusion is SchemaAuditConclusion.INCOMPLETE_SCHEMA_READ_ONLY:
        read_only_reason = "generated schema lacks required stable methods"
    else:
        read_only_reason = "exact schema is not in the human-approved write profiles"
    report = SchemaAuditReport(
        generated_at=generated_at or utc_now(),
        tool_version=__version__,
        platform=platform_name or sys.platform,
        architecture=architecture or platform.machine() or "unknown",
        codex_version=capabilities.codex_version,
        codex_binary_sha256=capabilities.codex_binary_sha256,
        schema_sha256=capabilities.schema_sha256,
        capability_fingerprint=capabilities.fingerprint,
        stable_methods=capabilities.stable_methods,
        experimental_methods=capabilities.experimental_methods,
        required_methods=tuple(sorted(BASELINE_METHODS)),
        missing_required_methods=missing,
        critical_fields=_critical_fields(capabilities),
        compared_profile_version=(comparison.codex_version if comparison else None),
        compared_profile_schema_sha256=(comparison.schema_sha256 if comparison else None),
        exact_profile_match=exact_profile is not None,
        differences=differences,
        conclusion=conclusion,
        write_enabled=write_enabled,
        read_only_reason=read_only_reason,
    ).seal()
    report.verify()
    return report


def audit_local_schema(*, executable: str | None = None) -> SchemaAuditReport:
    """Generate local schemas and return portable, read-only audit evidence."""

    return build_schema_audit_report(probe_capabilities(executable=executable))


def save_schema_audit_report(report: SchemaAuditReport, destination: Path) -> None:
    """Atomically persist one immutable versioned JSON report."""

    report.verify()
    private_atomic_create(destination, canonical_json_bytes(report))
