"""Sealed review requests and untrusted suggestion bundles for GUI hand-off."""

from __future__ import annotations

import contextlib
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from codex_session_manager.config import AppPaths, private_atomic_write
from codex_session_manager.hashing import (
    canonical_json_bytes,
    fingerprint,
    sealed_fingerprint,
    utc_now,
)

_SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class FrozenReviewModel(BaseModel):
    """Immutable request models that reject unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewOperation(StrEnum):
    CONVERSATION_CLEANUP = "conversation_cleanup"
    CONTEXT_TRIM = "context_trim"
    MEMORY_EDIT = "memory_edit"
    BACKUP = "backup"
    RESTORE = "restore"


class ReviewSource(StrEnum):
    CLI = "cli"
    SKILL = "skill"
    MCP = "mcp"
    HOOK = "hook"


class SuggestedAction(StrEnum):
    KEEP = "keep"
    ARCHIVE = "archive"
    EXCLUDE = "exclude"
    SUMMARY = "summary"
    PROTECT = "protect"
    DELETE = "delete"
    REPLACE = "replace"


_ALLOWED_ACTIONS: dict[ReviewOperation, frozenset[SuggestedAction]] = {
    ReviewOperation.CONVERSATION_CLEANUP: frozenset(
        {SuggestedAction.KEEP, SuggestedAction.ARCHIVE}
    ),
    ReviewOperation.CONTEXT_TRIM: frozenset(
        {
            SuggestedAction.KEEP,
            SuggestedAction.EXCLUDE,
            SuggestedAction.SUMMARY,
            SuggestedAction.PROTECT,
        }
    ),
    ReviewOperation.MEMORY_EDIT: frozenset(
        {
            SuggestedAction.KEEP,
            SuggestedAction.DELETE,
            SuggestedAction.REPLACE,
            SuggestedAction.PROTECT,
        }
    ),
}


class SuggestionTarget(FrozenReviewModel):
    target_id: str | None = None
    target_path: str | None = None
    source_fingerprint: str = Field(min_length=1)
    suggested_action: SuggestedAction
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_text: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if bool(self.target_id) == bool(self.target_path):
            raise ValueError("suggestion target must contain exactly one id or path")
        if self.suggested_action in {
            SuggestedAction.SUMMARY,
            SuggestedAction.REPLACE,
        } and (not self.suggested_text or not self.suggested_text.strip()):
            raise ValueError("summary/replace suggestion requires suggested_text")
        return self

    @property
    def key(self) -> str:
        return f"id:{self.target_id}" if self.target_id else f"path:{self.target_path}"


class SuggestionBundle(FrozenReviewModel):
    schema_version: Literal[1] = 1
    bundle_id: str = Field(pattern=_SAFE_IDENTIFIER_PATTERN)
    operation: ReviewOperation
    source: ReviewSource
    created_at: AwareDatetime
    expires_at: AwareDatetime
    targets: tuple[SuggestionTarget, ...]
    bundle_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        operation: ReviewOperation,
        source: ReviewSource,
        targets: tuple[SuggestionTarget, ...],
        lifetime: timedelta = timedelta(minutes=30),
    ) -> Self:
        created_at = utc_now()
        draft = cls(
            bundle_id=str(uuid4()),
            operation=operation,
            source=source,
            created_at=created_at,
            expires_at=created_at + lifetime,
            targets=targets,
        )
        return draft.model_copy(
            update={"bundle_sha256": sealed_fingerprint(draft, "bundle_sha256")}
        )

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        allowed = _ALLOWED_ACTIONS.get(self.operation)
        if allowed is None:
            raise ValueError(f"{self.operation.value} does not accept suggestion bundles")
        if not self.targets:
            raise ValueError("suggestion bundle must contain at least one target")
        seen: set[str] = set()
        for target in self.targets:
            if target.key in seen:
                raise ValueError(f"duplicate suggestion target: {target.key}")
            seen.add(target.key)
            if target.suggested_action not in allowed:
                raise ValueError(
                    f"{target.suggested_action.value} is not allowed for {self.operation.value}"
                )
        return self

    def verify(self) -> None:
        expected = sealed_fingerprint(self, "bundle_sha256")
        if not self.bundle_sha256 or self.bundle_sha256 != expected:
            raise ValueError("SuggestionBundle SHA-256 mismatch")
        if self.expires_at <= utc_now():
            raise ValueError("SuggestionBundle has expired")


class ReviewRequest(FrozenReviewModel):
    schema_version: Literal[1] = 1
    request_id: str = Field(pattern=_SAFE_IDENTIFIER_PATTERN)
    operation: ReviewOperation
    source: ReviewSource
    account_root_fingerprint: str = Field(min_length=1)
    target_ids: tuple[str, ...] = ()
    target_paths: tuple[str, ...] = ()
    suggestion_bundle_path: str | None = None
    created_at: AwareDatetime
    expires_at: AwareDatetime
    request_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        operation: ReviewOperation,
        source: ReviewSource,
        account_root_fingerprint: str,
        target_ids: tuple[str, ...] = (),
        target_paths: tuple[str, ...] = (),
        suggestion_bundle_path: Path | str | None = None,
        lifetime: timedelta = timedelta(minutes=30),
    ) -> Self:
        created_at = utc_now()
        draft = cls(
            request_id=str(uuid4()),
            operation=operation,
            source=source,
            account_root_fingerprint=account_root_fingerprint,
            target_ids=target_ids,
            target_paths=target_paths,
            suggestion_bundle_path=(
                str(suggestion_bundle_path) if suggestion_bundle_path is not None else None
            ),
            created_at=created_at,
            expires_at=created_at + lifetime,
        )
        return draft.model_copy(
            update={"request_sha256": sealed_fingerprint(draft, "request_sha256")}
        )

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("review request target_ids must be unique")
        if len(set(self.target_paths)) != len(self.target_paths):
            raise ValueError("review request target_paths must be unique")
        if not self.target_ids and not self.target_paths and not self.suggestion_bundle_path:
            raise ValueError("review request requires a target or suggestion bundle")
        if self.operation is ReviewOperation.CONTEXT_TRIM and (
            len(self.target_ids) != 1 or self.target_paths
        ):
            raise ValueError("context_trim requires exactly one conversation id")
        if self.operation is ReviewOperation.CONVERSATION_CLEANUP and self.target_paths:
            raise ValueError("conversation_cleanup does not accept file paths")
        if self.operation is ReviewOperation.MEMORY_EDIT and self.target_ids:
            raise ValueError("memory_edit does not accept conversation ids")
        return self

    def verify(self) -> None:
        expected = sealed_fingerprint(self, "request_sha256")
        if not self.request_sha256 or self.request_sha256 != expected:
            raise ValueError("ReviewRequest SHA-256 mismatch")
        if self.expires_at <= utc_now():
            raise ValueError("ReviewRequest has expired")


def codex_account_fingerprint(paths: AppPaths) -> str:
    """Bind requests to one resolved Codex account root without exposing its content."""

    return fingerprint({"codex_home": str(paths.codex_home.resolve(strict=False))})


def _resolve_private_child(path: Path, root: Path) -> Path:
    if path.is_symlink():
        raise ValueError("review data path must not be a symbolic link")
    resolved = path.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if resolved.parent != resolved_root:
        raise ValueError("review data path escaped its private store")
    return resolved


def _save_immutable(path: Path, payload: bytes) -> Path:
    if path.exists():
        if path.is_symlink():
            raise ValueError("immutable review data path must not be a symbolic link")
        if path.read_bytes() != payload:
            raise ValueError(f"immutable review data already exists with different bytes: {path}")
        return path
    private_atomic_write(path, payload)
    return path


class SuggestionBundleStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def path_for(self, bundle: SuggestionBundle) -> Path:
        return self.paths.suggestions_dir / f"suggestion-{bundle.bundle_id}.json"

    def save(self, bundle: SuggestionBundle) -> Path:
        bundle.verify()
        return _save_immutable(self.path_for(bundle), canonical_json_bytes(bundle))

    def load(self, path: Path) -> SuggestionBundle:
        resolved = _resolve_private_child(path, self.paths.suggestions_dir)
        bundle = SuggestionBundle.model_validate_json(resolved.read_bytes())
        bundle.verify()
        if resolved != self.path_for(bundle).resolve(strict=False):
            raise ValueError("suggestion bundle path does not match its sealed identity")
        return bundle


class ReviewRequestStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def path_for(self, request: ReviewRequest) -> Path:
        return self.paths.review_requests_dir / f"review-{request.request_id}.json"

    def save(self, request: ReviewRequest) -> Path:
        request.verify()
        if request.account_root_fingerprint != codex_account_fingerprint(self.paths):
            raise ValueError("review request is bound to another Codex account root")
        return _save_immutable(self.path_for(request), canonical_json_bytes(request))

    def load(self, path: Path) -> ReviewRequest:
        resolved = _resolve_private_child(path, self.paths.review_requests_dir)
        request = ReviewRequest.model_validate_json(resolved.read_bytes())
        request.verify()
        if resolved != self.path_for(request).resolve(strict=False):
            raise ValueError("review request path does not match its sealed identity")
        if request.account_root_fingerprint != codex_account_fingerprint(self.paths):
            raise ValueError("review request is bound to another Codex account root")
        if request.suggestion_bundle_path:
            bundle = SuggestionBundleStore(self.paths).load(Path(request.suggestion_bundle_path))
            if bundle.operation is not request.operation:
                raise ValueError("suggestion bundle operation does not match review request")
            requested_ids = set(request.target_ids)
            requested_paths = set(request.target_paths)
            for target in bundle.targets:
                if target.target_id and requested_ids and target.target_id not in requested_ids:
                    raise ValueError("suggestion target is outside the review request ids")
                if (
                    target.target_path
                    and requested_paths
                    and target.target_path not in requested_paths
                ):
                    raise ValueError("suggestion target is outside the review request paths")
        return request


class PendingReviewRequest(FrozenReviewModel):
    """Immutable queue reference retained until a GUI process accepts the request."""

    schema_version: Literal[1] = 1
    request_id: str = Field(pattern=_SAFE_IDENTIFIER_PATTERN)
    request_path: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)

    @classmethod
    def create(cls, request: ReviewRequest, request_path: Path) -> Self:
        return cls(
            request_id=request.request_id,
            request_path=str(request_path),
            request_sha256=request.request_sha256,
        )


class ReviewRequestQueue:
    """Private, idempotent queue for requests awaiting desktop acceptance."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def path_for(self, request: ReviewRequest) -> Path:
        return self.paths.pending_review_requests_dir / f"pending-{request.request_id}.json"

    def enqueue(self, request_path: Path) -> tuple[ReviewRequest, Path]:
        store = ReviewRequestStore(self.paths)
        request = store.load(request_path)
        canonical_request_path = store.path_for(request).resolve(strict=True)
        entry = PendingReviewRequest.create(request, canonical_request_path)
        queue_path = _save_immutable(self.path_for(request), canonical_json_bytes(entry))
        return request, queue_path

    def entry_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                (
                    path
                    for path in self.paths.pending_review_requests_dir.iterdir()
                    if path.name.startswith("pending-") and path.suffix == ".json"
                ),
                key=lambda path: path.name,
            )
        )

    def load(self, path: Path) -> PendingReviewRequest:
        resolved = _resolve_private_child(path, self.paths.pending_review_requests_dir)
        entry = PendingReviewRequest.model_validate_json(resolved.read_bytes())
        if resolved.name != f"pending-{entry.request_id}.json":
            raise ValueError("pending review path does not match its request identity")
        return entry

    def load_request(self, path: Path) -> ReviewRequest:
        entry = self.load(path)
        request = ReviewRequestStore(self.paths).load(Path(entry.request_path))
        if request.request_id != entry.request_id:
            raise ValueError("pending review entry points to another request id")
        if request.request_sha256 != entry.request_sha256:
            raise ValueError("pending review entry points to another request digest")
        return request

    def acknowledge(self, request: ReviewRequest) -> None:
        queue_path = self.path_for(request)
        if not queue_path.exists():
            return
        entry = self.load(queue_path)
        if entry.request_id != request.request_id:
            raise ValueError("pending review acknowledgement id mismatch")
        if entry.request_sha256 != request.request_sha256:
            raise ValueError("pending review acknowledgement digest mismatch")
        with contextlib.suppress(FileNotFoundError):
            queue_path.unlink()
