"""Application-owned append-only audit chain and trusted safety evidence."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from codex_session_manager.config import AppPaths
from codex_session_manager.hashing import (
    canonical_json_bytes,
    hash_file,
    sealed_fingerprint,
    utc_now,
)
from codex_session_manager.models import AuditEvent, BackupVerification

MAX_AUDIT_DETAIL_TEXT = 4096
SENSITIVE_KEYS = {
    "password",
    "passphrase",
    "secret",
    "token",
    "identity",
    "private_key",
    "content",
    "body",
    "message_text",
}


@dataclass(frozen=True, slots=True)
class VerifiedBackupEvidence:
    source_fingerprint: str
    manifest_sha256: str
    path: Path
    ciphertext_sha256: str
    ciphertext_size: int
    evidence_event_sha256: str

    def is_current(self) -> bool:
        try:
            if self.path.is_symlink() or not self.path.is_file():
                return False
            digest, size = hash_file(self.path)
        except (OSError, ValueError):
            return False
        return digest == self.ciphertext_sha256 and size == self.ciphertext_size


@dataclass(frozen=True, slots=True)
class TrustedArchiveEvidence:
    archived_at: datetime
    plan_sha256: str
    manifest_sha256: str
    evidence_event_sha256: str


def _safe_details(value: Any, *, key: str | None = None) -> Any:
    if key and key.casefold() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _safe_details(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_details(child) for child in value]
    if isinstance(value, str) and len(value) > MAX_AUDIT_DETAIL_TEXT:
        return value[:MAX_AUDIT_DETAIL_TEXT] + "…[truncated]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AuditStore:
    """Own a separate SQLite database; never open the Codex state database."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.connection = sqlite3.connect(self.paths.audit_db)
        self.connection.row_factory = sqlite3.Row
        with contextlib.suppress(OSError):
            os.chmod(self.paths.audit_db, 0o600)
        self._initialize()

    def __enter__(self) -> AuditStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                plan_sha256 TEXT,
                target_ids_json TEXT NOT NULL,
                result TEXT NOT NULL,
                details_json TEXT NOT NULL,
                previous_event_sha256 TEXT,
                event_sha256 TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS backup_coverage (
                thread_id TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                ciphertext_sha256 TEXT,
                ciphertext_size INTEGER,
                evidence_event_sha256 TEXT,
                PRIMARY KEY (thread_id, source_fingerprint, manifest_sha256)
            );
            CREATE TABLE IF NOT EXISTS trusted_archives (
                thread_id TEXT PRIMARY KEY,
                archived_at TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                evidence_event_sha256 TEXT
            );
            CREATE TABLE IF NOT EXISTS operations (
                plan_sha256 TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            );
            """
        )
        columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(backup_coverage)")
        }
        if "ciphertext_sha256" not in columns:
            self.connection.execute("ALTER TABLE backup_coverage ADD COLUMN ciphertext_sha256 TEXT")
        if "ciphertext_size" not in columns:
            self.connection.execute(
                "ALTER TABLE backup_coverage ADD COLUMN ciphertext_size INTEGER"
            )
        if "evidence_event_sha256" not in columns:
            self.connection.execute(
                "ALTER TABLE backup_coverage ADD COLUMN evidence_event_sha256 TEXT"
            )
        archive_columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(trusted_archives)")
        }
        if "evidence_event_sha256" not in archive_columns:
            self.connection.execute(
                "ALTER TABLE trusted_archives ADD COLUMN evidence_event_sha256 TEXT"
            )
        self.connection.commit()

    def append(
        self,
        *,
        event_type: str,
        actor: str,
        result: str,
        plan_sha256: str | None = None,
        target_ids: tuple[str, ...] = (),
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        with self.connection:
            previous_row = self.connection.execute(
                "SELECT event_sha256 FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous = str(previous_row[0]) if previous_row else None
            draft = AuditEvent(
                event_id=str(uuid4()),
                occurred_at=utc_now(),
                event_type=event_type,
                actor=actor,
                plan_sha256=plan_sha256,
                target_ids=target_ids,
                result=result,
                details=_safe_details(details or {}),
                previous_event_sha256=previous,
            )
            event = draft.seal()
            self.connection.execute(
                """
                INSERT INTO audit_events (
                    event_id, occurred_at, event_type, actor, plan_sha256,
                    target_ids_json, result, details_json,
                    previous_event_sha256, event_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.occurred_at.isoformat(),
                    event.event_type,
                    event.actor,
                    event.plan_sha256,
                    canonical_json_bytes(event.target_ids).decode("utf-8"),
                    event.result,
                    canonical_json_bytes(event.details).decode("utf-8"),
                    event.previous_event_sha256,
                    event.event_sha256,
                ),
            )
        return event

    def iter_events(self, *, limit: int = 100) -> Iterator[AuditEvent]:
        rows = self.connection.execute(
            "SELECT * FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)
        )
        for row in rows:
            yield self._event_from_row(row)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            event_id=row["event_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            event_type=row["event_type"],
            actor=row["actor"],
            plan_sha256=row["plan_sha256"],
            target_ids=tuple(json.loads(row["target_ids_json"])),
            result=row["result"],
            details=json.loads(row["details_json"]),
            previous_event_sha256=row["previous_event_sha256"],
            event_sha256=row["event_sha256"],
        )

    def _event_by_sha256(self, event_sha256: str) -> AuditEvent:
        row = self.connection.execute(
            "SELECT * FROM audit_events WHERE event_sha256 = ?", (event_sha256,)
        ).fetchone()
        if row is None:
            raise ValueError("safety evidence references a missing audit event")
        event = self._event_from_row(row)
        if event.event_sha256 != sealed_fingerprint(event, "event_sha256"):
            raise ValueError(f"audit event hash mismatch at {event.event_id}")
        return event

    def verify_chain(self) -> None:
        previous: str | None = None
        rows = self.connection.execute("SELECT * FROM audit_events ORDER BY sequence ASC")
        for row in rows:
            event = self._event_from_row(row)
            if event.previous_event_sha256 != previous:
                raise ValueError(f"audit chain predecessor mismatch at {event.event_id}")
            if event.event_sha256 != sealed_fingerprint(event, "event_sha256"):
                raise ValueError(f"audit event hash mismatch at {event.event_id}")
            previous = event.event_sha256

    def record_verified_backup(self, verification: BackupVerification, path: Path) -> None:
        verification = BackupVerification.model_validate(verification)
        manifest = verification.manifest
        if path.is_symlink():
            raise ValueError("verified backup evidence must not be a symbolic link")
        resolved_path = path.resolve(strict=True)
        if not resolved_path.is_file():
            raise ValueError("verified backup evidence is not a regular file")
        ciphertext_sha256, ciphertext_size = hash_file(resolved_path)
        event = self.append(
            event_type="backup.evidence",
            actor="csm-full-bundle-verifier",
            result="succeeded",
            target_ids=tuple(sorted(verification.embedded_source_fingerprints)),
            details={
                "manifest_sha256": manifest.manifest_sha256,
                "source_fingerprints": dict(
                    sorted(verification.embedded_source_fingerprints.items())
                ),
                "backup_path": str(resolved_path),
                "ciphertext_sha256": ciphertext_sha256,
                "ciphertext_size": ciphertext_size,
            },
        )
        with self.connection:
            for thread_id, source_fingerprint in verification.embedded_source_fingerprints.items():
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO backup_coverage (
                        thread_id, source_fingerprint, manifest_sha256, verified_at, backup_path,
                        ciphertext_sha256, ciphertext_size, evidence_event_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        source_fingerprint,
                        manifest.manifest_sha256,
                        utc_now().isoformat(),
                        str(resolved_path),
                        ciphertext_sha256,
                        ciphertext_size,
                        event.event_sha256,
                    ),
                )

    def verified_backup(
        self,
        thread_id: str,
        source_fingerprint: str,
        *,
        manifest_sha256: str | None = None,
    ) -> VerifiedBackupEvidence | None:
        if manifest_sha256 is None:
            row = self.connection.execute(
                """
                SELECT source_fingerprint, manifest_sha256, backup_path,
                       ciphertext_sha256, ciphertext_size, evidence_event_sha256
                FROM backup_coverage
                WHERE thread_id = ? AND source_fingerprint = ?
                ORDER BY verified_at DESC LIMIT 1
                """,
                (thread_id, source_fingerprint),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT source_fingerprint, manifest_sha256, backup_path,
                       ciphertext_sha256, ciphertext_size, evidence_event_sha256
                FROM backup_coverage
                WHERE thread_id = ? AND source_fingerprint = ? AND manifest_sha256 = ?
                ORDER BY verified_at DESC LIMIT 1
                """,
                (thread_id, source_fingerprint, manifest_sha256),
            ).fetchone()
        if not row:
            return None
        digest = row["ciphertext_sha256"]
        size = row["ciphertext_size"]
        evidence_event_sha256 = row["evidence_event_sha256"]
        if (
            not isinstance(digest, str)
            or not isinstance(size, int)
            or not isinstance(evidence_event_sha256, str)
        ):
            return None
        event = self._event_by_sha256(evidence_event_sha256)
        bindings = event.details.get("source_fingerprints")
        expected_path = str(row["backup_path"])
        expected_manifest = str(row["manifest_sha256"])
        if (
            event.event_type != "backup.evidence"
            or event.result != "succeeded"
            or not isinstance(bindings, Mapping)
            or bindings.get(thread_id) != source_fingerprint
            or tuple(sorted(str(value) for value in bindings)) != event.target_ids
            or event.details.get("manifest_sha256") != expected_manifest
            or event.details.get("backup_path") != expected_path
            or event.details.get("ciphertext_sha256") != digest
            or event.details.get("ciphertext_size") != size
        ):
            raise ValueError("backup coverage row is not bound to its audit event")
        return VerifiedBackupEvidence(
            source_fingerprint=str(row["source_fingerprint"]),
            manifest_sha256=expected_manifest,
            path=Path(expected_path),
            ciphertext_sha256=digest,
            ciphertext_size=size,
            evidence_event_sha256=evidence_event_sha256,
        )

    def record_trusted_archive(
        self,
        *,
        thread_id: str,
        plan_sha256: str,
        manifest_sha256: str,
        archived_at: datetime | None = None,
    ) -> None:
        effective_archived_at = archived_at or utc_now()
        event = self.append(
            event_type="archive.evidence",
            actor="csm-postcondition-verifier",
            result="succeeded",
            plan_sha256=plan_sha256,
            target_ids=(thread_id,),
            details={
                "manifest_sha256": manifest_sha256,
                "archived_at": effective_archived_at.isoformat(),
            },
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO trusted_archives (
                    thread_id, archived_at, plan_sha256, manifest_sha256,
                    evidence_event_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    effective_archived_at.isoformat(),
                    plan_sha256,
                    manifest_sha256,
                    event.event_sha256,
                ),
            )

    def trusted_archive(self, thread_id: str) -> TrustedArchiveEvidence | None:
        row = self.connection.execute(
            """
            SELECT archived_at, plan_sha256, manifest_sha256, evidence_event_sha256
            FROM trusted_archives WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()
        if not row:
            return None
        evidence_event_sha256 = row["evidence_event_sha256"]
        if not isinstance(evidence_event_sha256, str):
            return None
        archived_at = datetime.fromisoformat(row["archived_at"])
        plan_sha256 = str(row["plan_sha256"])
        manifest_sha256 = str(row["manifest_sha256"])
        event = self._event_by_sha256(evidence_event_sha256)
        if (
            event.event_type != "archive.evidence"
            or event.result != "succeeded"
            or event.plan_sha256 != plan_sha256
            or event.target_ids != (thread_id,)
            or event.details.get("manifest_sha256") != manifest_sha256
            or event.details.get("archived_at") != archived_at.isoformat()
        ):
            raise ValueError("trusted archive row is not bound to its audit event")
        return TrustedArchiveEvidence(
            archived_at=archived_at,
            plan_sha256=plan_sha256,
            manifest_sha256=manifest_sha256,
            evidence_event_sha256=evidence_event_sha256,
        )

    def invalidate_trusted_archive(self, *, thread_id: str, plan_sha256: str) -> None:
        """Remove an archive-age credential before attempting an unarchive."""

        trusted = self.trusted_archive(thread_id)
        if trusted is None:
            return
        self.append(
            event_type="archive.evidence.invalidate",
            actor="csm-pre-unarchive-gate",
            result="succeeded",
            plan_sha256=plan_sha256,
            target_ids=(thread_id,),
            details={
                "previous_archive_event_sha256": trusted.evidence_event_sha256,
                "previous_manifest_sha256": trusted.manifest_sha256,
            },
        )
        with self.connection:
            self.connection.execute(
                "DELETE FROM trusted_archives WHERE thread_id = ?", (thread_id,)
            )

    def begin_operation(self, *, plan_sha256: str, action: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO operations (plan_sha256, action, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (plan_sha256, action, utc_now().isoformat()),
            )

    def finish_operation(self, *, plan_sha256: str, status: str, error: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE operations SET status = ?, finished_at = ?, error = ?
                WHERE plan_sha256 = ?
                """,
                (status, utc_now().isoformat(), error, plan_sha256),
            )
