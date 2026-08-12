"""Normalized immutable domain models used by every front end."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from codex_session_manager.hashing import fingerprint, sealed_fingerprint, utc_now


class FrozenModel(BaseModel):
    """Reject unknown fields and prevent attribute reassignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ThreadStatus(StrEnum):
    NOT_LOADED = "notLoaded"
    IDLE = "idle"
    ACTIVE = "active"
    SYSTEM_ERROR = "systemError"
    UNKNOWN = "unknown"


class ItemKind(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    DEVELOPER_MESSAGE = "developer_message"
    SYSTEM_MESSAGE = "system_message"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_CHANGE = "file_change"
    VERIFICATION = "verification"
    APPROVAL = "approval"
    ERROR = "error"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


class PlanAction(StrEnum):
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    PURGE = "purge"
    BACKUP = "backup"
    RESTORE = "restore"
    IMPORT = "import"
    TRIM = "trim"


class TrimAction(StrEnum):
    KEEP = "keep"
    EXCLUDE = "exclude"
    SUMMARY = "summary"
    PROTECT = "protect"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class ThreadItemSnapshot(FrozenModel):
    id: str
    turn_id: str
    kind: ItemKind
    raw_type: str
    role: str | None = None
    text: str = ""
    created_at: AwareDatetime | None = None
    token_estimate: int = Field(default=0, ge=0)
    depends_on: tuple[str, ...] = ()
    hard_protected: bool = False
    protected_reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(self)


class TurnSnapshot(FrozenModel):
    id: str
    status: str
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    items: tuple[ThreadItemSnapshot, ...] = ()

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(self)


class ThreadSnapshot(FrozenModel):
    id: str
    title: str = ""
    preview: str = ""
    cwd: str | None = None
    git_remote: str | None = None
    source_kind: str = "unknown"
    model_provider: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    status: ThreadStatus = ThreadStatus.UNKNOWN
    archived: bool = False
    pinned: bool = False
    ephemeral: bool = False
    parent_id: str | None = None
    session_id: str | None = None
    forked_from_id: str | None = None
    spawned_descendant_ids: tuple[str, ...] = ()
    turns: tuple[TurnSnapshot, ...] = ()
    content_complete: bool = False
    size_bytes: int = Field(default=0, ge=0)
    raw_path: str | None = None
    mapping_complete: bool = True
    unknown_item_count: int = Field(default=0, ge=0)

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(self.turns)

    @property
    def state_fingerprint(self) -> str:
        return fingerprint(self)

    @property
    def trim_fingerprint(self) -> str:
        """Fingerprint model-visible content without volatile runtime status."""

        return fingerprint(
            {
                "id": self.id,
                "cwd": self.cwd,
                "git_remote": self.git_remote,
                "turns": self.turns,
                "mapping_complete": self.mapping_complete,
                "unknown_item_count": self.unknown_item_count,
            }
        )

    @property
    def management_fingerprint(self) -> str:
        """Fingerprint all state that must remain unchanged before a write."""

        return fingerprint(
            {
                "id": self.id,
                "title": self.title,
                "preview": self.preview,
                "cwd": self.cwd,
                "git_remote": self.git_remote,
                "source_kind": self.source_kind,
                "model_provider": self.model_provider,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "archived": self.archived,
                "pinned": self.pinned,
                "ephemeral": self.ephemeral,
                "parent_id": self.parent_id,
                "session_id": self.session_id,
                "forked_from_id": self.forked_from_id,
                "spawned_descendant_ids": self.spawned_descendant_ids,
                "size_bytes": self.size_bytes,
                "mapping_complete": self.mapping_complete,
                "unknown_item_count": self.unknown_item_count,
                "content_complete": self.content_complete,
                "content_fingerprint": self.content_fingerprint if self.content_complete else None,
            }
        )

    @property
    def backup_fingerprint(self) -> str:
        """Fingerprint recoverable state while ignoring the archive-location bit."""

        return fingerprint(
            {
                "id": self.id,
                "title": self.title,
                "preview": self.preview,
                "cwd": self.cwd,
                "git_remote": self.git_remote,
                "source_kind": self.source_kind,
                "model_provider": self.model_provider,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "pinned": self.pinned,
                "ephemeral": self.ephemeral,
                "parent_id": self.parent_id,
                "session_id": self.session_id,
                "forked_from_id": self.forked_from_id,
                "spawned_descendant_ids": self.spawned_descendant_ids,
                "size_bytes": self.size_bytes,
                "mapping_complete": self.mapping_complete,
                "unknown_item_count": self.unknown_item_count,
                "content_complete": self.content_complete,
                "content_fingerprint": self.content_fingerprint if self.content_complete else None,
            }
        )

    @property
    def token_estimate(self) -> int:
        return sum(item.token_estimate for turn in self.turns for item in turn.items)


class CapabilityMatrix(FrozenModel):
    codex_version: str | None = None
    codex_binary_path: str | None = None
    codex_binary_sha256: str | None = None
    initialize_fingerprint: str
    schema_sha256: str | None = None
    stable_methods: tuple[str, ...] = ()
    experimental_methods: tuple[str, ...] = ()
    experimental_api: bool = False
    fork_supports_last_turn_id: bool = False
    schema_complete: bool = False
    read_only_reason: str | None = None

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)

    @property
    def write_enabled(self) -> bool:
        return self.schema_complete and self.read_only_reason is None

    def supports(self, method: str) -> bool:
        return method in self.stable_methods or method in self.experimental_methods

    def require_write(self, method: str) -> None:
        if not self.write_enabled:
            reason = self.read_only_reason or "App Server schema is not trusted"
            raise ValueError(f"write capability disabled: {reason}")
        if method in self.stable_methods:
            return
        if method in self.experimental_methods and self.experimental_api:
            return
        if method in self.experimental_methods:
            raise ValueError(
                f"experimental method requires an explicitly negotiated connection: {method}"
            )
        raise ValueError(f"required App Server method is unavailable: {method}")


class PlanTarget(FrozenModel):
    root_thread_id: str
    affected_thread_ids: tuple[str, ...]
    snapshot_fingerprints: dict[str, str]
    reasons: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.LOW

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        ids = set(self.affected_thread_ids)
        if len(ids) != len(self.affected_thread_ids):
            raise ValueError("affected_thread_ids must not contain duplicates")
        if self.root_thread_id not in ids:
            raise ValueError("affected_thread_ids must include root_thread_id")
        if ids != set(self.snapshot_fingerprints):
            raise ValueError("snapshot fingerprints must cover the exact descendant closure")
        return self


class ActionPlan(FrozenModel):
    schema_version: Literal[1] = 1
    plan_id: str
    action: PlanAction
    created_at: AwareDatetime
    expires_at: AwareDatetime
    capability_fingerprint: str
    targets: tuple[PlanTarget, ...]
    prerequisites: tuple[str, ...] = ()
    options: dict[str, Any] = Field(default_factory=dict)
    plan_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        action: PlanAction,
        capability_fingerprint: str,
        targets: tuple[PlanTarget, ...],
        prerequisites: tuple[str, ...] = (),
        options: dict[str, Any] | None = None,
        lifetime: timedelta = timedelta(hours=24),
    ) -> Self:
        created_at = utc_now()
        draft = cls(
            plan_id=str(uuid4()),
            action=action,
            created_at=created_at,
            expires_at=created_at + lifetime,
            capability_fingerprint=capability_fingerprint,
            targets=targets,
            prerequisites=prerequisites,
            options=options or {},
        )
        return draft.model_copy(update={"plan_sha256": sealed_fingerprint(draft, "plan_sha256")})

    def verify(self) -> None:
        expected = sealed_fingerprint(self, "plan_sha256")
        if not self.plan_sha256 or expected != self.plan_sha256:
            raise ValueError("ActionPlan SHA-256 mismatch")
        if self.expires_at <= utc_now():
            raise ValueError("ActionPlan has expired")
        if len(self.targets) > 100:
            raise ValueError("ActionPlan exceeds the 100-root batch limit")
        seen: set[str] = set()
        for target in self.targets:
            overlap = seen & set(target.affected_thread_ids)
            if overlap:
                raise ValueError(
                    "ActionPlan target closures overlap: " + ", ".join(sorted(overlap))
                )
            seen.update(target.affected_thread_ids)


class BackupEntry(FrozenModel):
    path: str
    kind: Literal["logical", "raw", "attachment", "sidecar"]
    size: int = Field(ge=0)
    sha256: str
    thread_id: str | None = None


class BackupManifest(FrozenModel):
    schema_version: Literal[1] = 1
    backup_id: str
    created_at: AwareDatetime
    tool_version: str
    encryption: Literal["age-recipient", "age-passphrase"]
    entries: tuple[BackupEntry, ...]
    source_fingerprints: dict[str, str]
    notes: tuple[str, ...] = ()
    manifest_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(
            update={"manifest_sha256": sealed_fingerprint(self, "manifest_sha256")}
        )

    def verify(self) -> None:
        if self.manifest_sha256 != sealed_fingerprint(self, "manifest_sha256"):
            raise ValueError("BackupManifest SHA-256 mismatch")
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("BackupManifest contains duplicate paths")
        logical_thread_ids = [
            entry.thread_id
            for entry in self.entries
            if entry.kind == "logical" and entry.thread_id is not None
        ]
        if len(logical_thread_ids) != len(set(logical_thread_ids)):
            raise ValueError("BackupManifest contains duplicate logical thread entries")
        source_ids = set(self.source_fingerprints)
        if set(logical_thread_ids) != source_ids:
            raise ValueError(
                "BackupManifest source fingerprints must match logical thread entries exactly"
            )
        for entry in self.entries:
            if entry.kind == "logical" and entry.thread_id is None:
                raise ValueError("logical backup entries require a thread_id")
            if entry.thread_id is not None and entry.thread_id not in source_ids:
                raise ValueError("backup entry references an undeclared source thread")


class BackupVerification(FrozenModel):
    """Evidence produced only after decrypting and checking an entire backup."""

    manifest: BackupManifest
    embedded_source_fingerprints: dict[str, str]

    @model_validator(mode="after")
    def validate_embedded_bindings(self) -> Self:
        self.manifest.verify()
        if self.embedded_source_fingerprints != self.manifest.source_fingerprints:
            raise ValueError(
                "verified embedded snapshots must match manifest source fingerprints exactly"
            )
        return self


class ImportDisposition(StrEnum):
    CREATE = "create"
    SKIP_EXACT = "skip_exact"
    PREFER_COMPLETE = "prefer_complete"
    KEEP_DIVERGED = "keep_diverged"
    QUARANTINE = "quarantine"


class ImportCandidate(FrozenModel):
    candidate_id: str
    source_type: str
    source_account: str | None = None
    source_thread_id: str | None = None
    branch_path: tuple[str, ...] = ()
    title: str = ""
    fingerprint: str
    prefix_fingerprint: str | None = None
    disposition: ImportDisposition
    mapped_cwd: str | None = None
    mapped_git_remote: str | None = None
    mapping_confirmed: bool = False
    reasons: tuple[str, ...] = ()


class ImportPlan(FrozenModel):
    schema_version: Literal[1] = 1
    plan_id: str
    created_at: AwareDatetime
    source_sha256: str
    capability_fingerprint: str
    candidates: tuple[ImportCandidate, ...]
    plan_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(update={"plan_sha256": sealed_fingerprint(self, "plan_sha256")})

    def verify(self) -> None:
        if self.plan_sha256 != sealed_fingerprint(self, "plan_sha256"):
            raise ValueError("ImportPlan SHA-256 mismatch")
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("ImportPlan contains duplicate candidate ids")


class TrimSelection(FrozenModel):
    target_id: str
    target_level: Literal["turn", "item"] = "turn"
    action: TrimAction
    summary: str | None = None
    reason: str = ""
    suggested: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    protected_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.action is TrimAction.SUMMARY and not (self.summary or "").strip():
            raise ValueError("summary action requires non-empty summary text")
        if self.protected_reasons and self.action in {TrimAction.EXCLUDE, TrimAction.SUMMARY}:
            raise ValueError("hard-protected targets cannot be excluded or summarized")
        return self


class TrimPlan(FrozenModel):
    schema_version: Literal[1] = 1
    plan_id: str
    source_thread_id: str
    source_thread_fingerprint: str
    source_turn_id: str | None = None
    trigger: Literal["manual", "auto", "hook"] = "manual"
    created_at: AwareDatetime
    capability_fingerprint: str
    selections: tuple[TrimSelection, ...]
    estimated_tokens_before: int = Field(ge=0)
    estimated_tokens_after: int = Field(ge=0)
    plan_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        source_thread: ThreadSnapshot,
        capability_fingerprint: str,
        selections: tuple[TrimSelection, ...],
        estimated_tokens_after: int,
        trigger: Literal["manual", "auto", "hook"] = "manual",
        source_turn_id: str | None = None,
    ) -> Self:
        draft = cls(
            plan_id=str(uuid4()),
            source_thread_id=source_thread.id,
            source_thread_fingerprint=source_thread.trim_fingerprint,
            source_turn_id=source_turn_id,
            trigger=trigger,
            created_at=utc_now(),
            capability_fingerprint=capability_fingerprint,
            selections=selections,
            estimated_tokens_before=source_thread.token_estimate,
            estimated_tokens_after=estimated_tokens_after,
        )
        return draft.model_copy(update={"plan_sha256": sealed_fingerprint(draft, "plan_sha256")})

    def verify(self) -> None:
        if self.plan_sha256 != sealed_fingerprint(self, "plan_sha256"):
            raise ValueError("TrimPlan SHA-256 mismatch")
        if self.estimated_tokens_after > self.estimated_tokens_before:
            raise ValueError("TrimPlan cannot increase estimated context")
        targets = [selection.target_id for selection in self.selections]
        if len(targets) != len(set(targets)):
            raise ValueError("TrimPlan contains duplicate selection targets")


class ProjectionEntry(FrozenModel):
    source_id: str
    action: TrimAction
    text: str
    source_fingerprint: str


class ContextProjection(FrozenModel):
    schema_version: Literal[1] = 1
    projection_id: str
    source_thread_id: str
    source_thread_fingerprint: str
    trim_plan_sha256: str
    created_at: AwareDatetime
    entries: tuple[ProjectionEntry, ...]
    excluded_ids: tuple[str, ...]
    manifest_text: str
    projection_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(
            update={"projection_sha256": sealed_fingerprint(self, "projection_sha256")}
        )

    def verify(self) -> None:
        if self.projection_sha256 != sealed_fingerprint(self, "projection_sha256"):
            raise ValueError("ContextProjection SHA-256 mismatch")


class AuditEvent(FrozenModel):
    schema_version: Literal[1] = 1
    event_id: str
    occurred_at: AwareDatetime
    event_type: str
    actor: str
    plan_sha256: str | None = None
    target_ids: tuple[str, ...] = ()
    result: str
    details: dict[str, Any] = Field(default_factory=dict)
    previous_event_sha256: str | None = None
    event_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(update={"event_sha256": sealed_fingerprint(self, "event_sha256")})
