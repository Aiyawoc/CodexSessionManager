"""Redacted evidence records for explicitly staged manual acceptance."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import AwareDatetime, model_validator

from codex_session_manager.config import private_atomic_create
from codex_session_manager.hashing import (
    canonical_json_bytes,
    sealed_fingerprint,
    sha256_bytes,
    utc_now,
)
from codex_session_manager.models import FrozenModel
from codex_session_manager.schema_audit import SchemaAuditReport
from codex_session_manager.version import __version__

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class AcceptanceScope(StrEnum):
    MACOS_REAL_ACCOUNT = "macos_real_account_manual"
    MACOS_COCOA_GUI = "macos_cocoa_gui_manual"
    WINDOWS_RUNNER_BUNDLE = "windows_runner_bundle"


class AcceptanceStageName(StrEnum):
    DOCTOR = "doctor"
    READ_INVENTORY = "read_inventory"
    GUI_TRIM_PLAN_SAVED = "gui_trim_plan_saved"
    DERIVED_THREAD_CREATED = "derived_thread_created"
    SOURCE_UNCHANGED = "source_unchanged"
    DERIVED_PROJECTION_VERIFIED = "derived_projection_verified"
    BACKUP_CREATED = "backup_created"
    BACKUP_VERIFIED = "backup_verified"
    AUDIT_VERIFIED = "audit_verified"
    DERIVED_ARCHIVED = "derived_archived"
    REREAD_VERIFIED = "reread_verified"
    COCOA_WINDOW_INPUT = "cocoa_window_input"
    WINDOWS_RUNNER = "windows_runner"
    WINDOWS_BUNDLE = "windows_bundle"


class AcceptanceStageResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class AcceptanceStage(FrozenModel):
    name: AcceptanceStageName
    result: AcceptanceStageResult
    evidence_sha256: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.evidence_sha256 is not None and _SHA256_RE.fullmatch(self.evidence_sha256) is None:
            raise ValueError("stage evidence_sha256 must be a lowercase SHA-256")
        return self


class AcceptanceReport(FrozenModel):
    """Content-free evidence summary; it can never claim production readiness."""

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    tool_version: str
    scope: AcceptanceScope
    schema_report_sha256: str
    schema_sha256: str | None = None
    task_id_hashes: tuple[str, ...] = ()
    plan_sha256s: tuple[str, ...] = ()
    backup_manifest_sha256s: tuple[str, ...] = ()
    audit_sha256: str | None = None
    stages: tuple[AcceptanceStage, ...]
    production_ready: Literal[False] = False
    limitations: tuple[str, ...] = (
        "no-restore-or-import",
        "no-real-hook-install",
        "not-production-acceptance",
    )
    report_sha256: str = ""

    @model_validator(mode="after")
    def validate_hashes_and_stages(self) -> Self:
        hashes = (
            self.schema_report_sha256,
            *self.task_id_hashes,
            *self.plan_sha256s,
            *self.backup_manifest_sha256s,
        )
        if self.schema_sha256 is not None:
            hashes = (*hashes, self.schema_sha256)
        if self.audit_sha256 is not None:
            hashes = (*hashes, self.audit_sha256)
        if any(_SHA256_RE.fullmatch(value) is None for value in hashes):
            raise ValueError("acceptance evidence must use lowercase SHA-256 values")
        names = [stage.name for stage in self.stages]
        if not names:
            raise ValueError("acceptance report must contain at least one stage")
        if len(names) != len(set(names)):
            raise ValueError("acceptance stages must not contain duplicates")
        return self

    def seal(self) -> Self:
        return self.model_copy(update={"report_sha256": sealed_fingerprint(self, "report_sha256")})

    def verify(self) -> None:
        if self.report_sha256 != sealed_fingerprint(self, "report_sha256"):
            raise ValueError("AcceptanceReport SHA-256 mismatch")


def hash_task_identifier(thread_id: str) -> str:
    """Hash a task identifier with a domain separator before recording it."""

    normalized = thread_id.strip()
    if not normalized:
        raise ValueError("thread id must not be empty")
    return sha256_bytes(f"csm-acceptance-thread-id-v1\0{normalized}".encode())


def create_acceptance_report(
    *,
    scope: AcceptanceScope,
    schema_report: SchemaAuditReport,
    stages: tuple[AcceptanceStage, ...],
    thread_ids: tuple[str, ...] = (),
    plan_sha256s: tuple[str, ...] = (),
    backup_manifest_sha256s: tuple[str, ...] = (),
    audit_sha256: str | None = None,
) -> AcceptanceReport:
    schema_report.verify()
    report = AcceptanceReport(
        generated_at=utc_now(),
        tool_version=__version__,
        scope=scope,
        schema_report_sha256=schema_report.report_sha256,
        schema_sha256=schema_report.schema_sha256,
        task_id_hashes=tuple(sorted({hash_task_identifier(value) for value in thread_ids})),
        plan_sha256s=tuple(sorted(set(plan_sha256s))),
        backup_manifest_sha256s=tuple(sorted(set(backup_manifest_sha256s))),
        audit_sha256=audit_sha256,
        stages=stages,
    ).seal()
    report.verify()
    return report


def save_acceptance_report(report: AcceptanceReport, destination: Path) -> None:
    report.verify()
    private_atomic_create(destination, canonical_json_bytes(report))
