"""Normalized, portable evidence for App Server operation contracts."""

from __future__ import annotations

import platform
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, field_validator, model_validator

from codex_session_manager.app_server import probe_capabilities
from codex_session_manager.config import private_atomic_create
from codex_session_manager.hashing import canonical_json_bytes, sealed_fingerprint, utc_now
from codex_session_manager.models import (
    CapabilityMatrix,
    FrozenModel,
    OperationCapability,
    OperationName,
)
from codex_session_manager.version import __version__


class SchemaAuditConclusion(StrEnum):
    COMPATIBLE = "compatible"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


_ABSOLUTE_PATH = re.compile(r"(?<![\w])/(?:[^\s,;:()\]\}]+/)+[^\s,;:()\]\}]+")
_WINDOWS_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?:[^\s,;:()\]\}]+[\\/])*[^\s,;:()\]\}]+")


def _portable_probe_error(error: str | None) -> str | None:
    """Keep a bounded diagnostic while removing machine-specific paths."""

    if error is None:
        return None
    message = str(error).strip() or "unknown probe error"
    home = str(Path.home().resolve(strict=False))
    message = message.replace(home, "<home>")
    message = _ABSOLUTE_PATH.sub("<private-path>", message)
    message = _WINDOWS_PATH.sub("<private-path>", message)
    username = Path.home().name
    if username:
        message = re.sub(rf"(?<![\w]){re.escape(username)}(?![\w])", "<user>", message)
    return message[:512]


class SchemaAuditReport(FrozenModel):
    """Immutable evidence that serializes operation capabilities directly."""

    schema_version: Literal[2] = 2
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
    operation_capabilities: tuple[OperationCapability, ...]
    probe_error: str | None = None
    conclusion: SchemaAuditConclusion
    report_sha256: str = ""

    @field_validator("probe_error")
    @classmethod
    def redact_probe_error(cls, value: str | None) -> str | None:
        return _portable_probe_error(value)

    def seal(self) -> Self:
        return self.model_copy(update={"report_sha256": sealed_fingerprint(self, "report_sha256")})

    def verify(self) -> None:
        if self.report_sha256 != sealed_fingerprint(self, "report_sha256"):
            raise ValueError("SchemaAuditReport SHA-256 mismatch")

    @model_validator(mode="after")
    def validate_conclusion(self) -> Self:
        names = tuple(capability.operation for capability in self.operation_capabilities)
        if len(names) != len(OperationName) or set(names) != set(OperationName):
            raise ValueError("operation_capabilities must contain each operation exactly once")
        expected = (
            SchemaAuditConclusion.UNAVAILABLE
            if self.probe_error is not None
            else (
                SchemaAuditConclusion.COMPATIBLE
                if all(capability.available for capability in self.operation_capabilities)
                else SchemaAuditConclusion.PARTIAL
            )
        )
        if self.conclusion is not expected:
            raise ValueError("schema audit conclusion does not match operation capabilities")
        return self


def build_schema_audit_report(
    capabilities: CapabilityMatrix,
    *,
    generated_at: AwareDatetime | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> SchemaAuditReport:
    """Classify an already-probed matrix without re-evaluating its schema."""

    operation_capabilities = tuple(capabilities.operation_capabilities)
    if capabilities.probe_error is not None:
        conclusion = SchemaAuditConclusion.UNAVAILABLE
    elif all(capability.available for capability in operation_capabilities):
        conclusion = SchemaAuditConclusion.COMPATIBLE
    else:
        conclusion = SchemaAuditConclusion.PARTIAL
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
        operation_capabilities=operation_capabilities,
        probe_error=_portable_probe_error(capabilities.probe_error),
        conclusion=conclusion,
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
