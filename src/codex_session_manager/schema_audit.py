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


def build_schema_audit_report(
    capabilities: CapabilityMatrix,
    *,
    generated_at: AwareDatetime | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> SchemaAuditReport:
    """Classify an already-probed capability matrix without any writes."""

    differences = (
        SchemaDifference(
            kind=SchemaDifferenceKind.UNKNOWN_PROFILE,
            subject="App Server schema",
            actual=capabilities.schema_sha256,
        ),
    )
    missing = tuple(sorted(BASELINE_METHODS - set(capabilities.stable_methods)))
    if capabilities.schema_sha256 is None or capabilities.codex_binary_sha256 is None:
        conclusion = SchemaAuditConclusion.UNAVAILABLE_READ_ONLY
    elif missing or not capabilities.schema_complete:
        conclusion = SchemaAuditConclusion.INCOMPLETE_SCHEMA_READ_ONLY
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
        read_only_reason = "operation contract results are available in the capability matrix"
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
        compared_profile_version=None,
        compared_profile_schema_sha256=None,
        exact_profile_match=False,
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
