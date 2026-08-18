"""Plan-gated management of explicitly registered local memory files."""

from __future__ import annotations

import contextlib
import difflib
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from codex_session_manager.audit import AuditStore
from codex_session_manager.config import (
    AppPaths,
    private_atomic_create,
    private_atomic_write,
)
from codex_session_manager.hashing import (
    canonical_json_bytes,
    fingerprint,
    sealed_fingerprint,
    sha256_bytes,
    utc_now,
)
from codex_session_manager.models import FrozenModel

MAX_MEMORY_FILE_BYTES: Final[int] = 5 * 1024 * 1024
SUPPORTED_MEMORY_SUFFIXES: Final[frozenset[str]] = frozenset({".md", ".markdown", ".mdx", ".txt"})
INSTRUCTION_FILENAMES: Final[frozenset[str]] = frozenset(
    {"agents.md", "claude.md", ".cursorrules", "copilot-instructions.md"}
)
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,2})[ \t]+(.+?)\s*(?:\r?\n|\r)?$")
_LIST_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)(?:[-+*]|\d+[.)])[ \t]+")
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")


class MemoryAction(StrEnum):
    KEEP = "keep"
    DELETE = "delete"
    REPLACE = "replace"
    PROTECT = "protect"


class MemorySegmentKind(StrEnum):
    FRONT_MATTER = "front_matter"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    WHITESPACE = "whitespace"
    RAW = "raw"


class MemorySource(FrozenModel):
    schema_version: Literal[1] = 1
    source_id: str
    root_path: str
    relative_path: str
    allow_instruction_file: bool = False
    created_at: AwareDatetime

    @property
    def path(self) -> Path:
        return Path(self.root_path) / self.relative_path

    @classmethod
    def create(
        cls,
        *,
        root_path: Path,
        file_path: Path,
        allow_instruction_file: bool = False,
    ) -> Self:
        root, target = validate_memory_path(
            root_path,
            file_path,
            allow_instruction_file=allow_instruction_file,
        )
        relative = target.relative_to(root).as_posix()
        source_id = sha256_bytes(f"csm-memory-source-v1\0{root}\0{relative}".encode())
        return cls(
            source_id=source_id,
            root_path=str(root),
            relative_path=relative,
            allow_instruction_file=allow_instruction_file,
            created_at=utc_now(),
        )


class MemorySourceRegistryDocument(FrozenModel):
    schema_version: Literal[1] = 1
    sources: tuple[MemorySource, ...] = ()


class MemorySegment(FrozenModel):
    segment_id: str
    kind: MemorySegmentKind
    heading_path: tuple[str, ...] = ()
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    text: str
    content_sha256: str
    protected: bool = False
    protection_reason: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_byte < self.start_byte:
            raise ValueError("memory segment byte range is inverted")
        if self.content_sha256 != sha256_bytes(self.text.encode("utf-8")):
            raise ValueError("memory segment content SHA-256 mismatch")
        if self.protected and not self.protection_reason:
            raise ValueError("protected memory segment requires a reason")
        return self


class MemorySnapshot(FrozenModel):
    schema_version: Literal[1] = 1
    source_id: str
    root_path: str
    relative_path: str
    content_sha256: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    inode: int = Field(ge=0)
    mode: int = Field(ge=0)
    utf8_bom: bool = False
    newline: str = "\n"
    segments: tuple[MemorySegment, ...] = ()
    captured_at: AwareDatetime

    @property
    def path(self) -> Path:
        return Path(self.root_path) / self.relative_path

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    @property
    def bytes(self) -> bytes:
        body = self.text.encode("utf-8")
        return (b"\xef\xbb\xbf" if self.utf8_bom else b"") + body

    @property
    def source_fingerprint(self) -> str:
        return fingerprint(
            {
                "source_id": self.source_id,
                "relative_path": self.relative_path,
                "content_sha256": self.content_sha256,
                "size_bytes": self.size_bytes,
                "mtime_ns": self.mtime_ns,
                "inode": self.inode,
                "mode": self.mode,
            }
        )

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.content_sha256 != sha256_bytes(self.bytes):
            raise ValueError("memory snapshot content SHA-256 mismatch")
        if self.size_bytes != len(self.bytes):
            raise ValueError("memory snapshot size mismatch")
        cursor = 3 if self.utf8_bom else 0
        for segment in self.segments:
            if segment.start_byte != cursor:
                raise ValueError("memory segments do not form a contiguous byte range")
            cursor = segment.end_byte
        if cursor != self.size_bytes:
            raise ValueError("memory segments do not cover the complete file")
        return self


class MemorySelection(FrozenModel):
    segment_id: str
    action: MemoryAction
    replacement: str | None = None
    reason: str = ""
    suggested: bool = False

    @model_validator(mode="after")
    def validate_replacement(self) -> Self:
        if self.action is MemoryAction.REPLACE and self.replacement is None:
            raise ValueError("replace selection requires replacement text")
        if self.action is not MemoryAction.REPLACE and self.replacement is not None:
            raise ValueError("only replace selection accepts replacement text")
        return self


class MemoryPlan(FrozenModel):
    schema_version: Literal[1] = 1
    plan_id: str
    source_id: str
    source_path: str
    source_fingerprint: str
    created_at: AwareDatetime
    selections: tuple[MemorySelection, ...]
    result_content_sha256: str
    diff_sha256: str
    plan_sha256: str = ""

    @classmethod
    def create(
        cls,
        snapshot: MemorySnapshot,
        selections: tuple[MemorySelection, ...],
    ) -> Self:
        validate_memory_selections(snapshot, selections)
        result = render_memory(snapshot, selections)
        diff = memory_unified_diff(snapshot, result)
        draft = cls(
            plan_id=str(uuid4()),
            source_id=snapshot.source_id,
            source_path=snapshot.relative_path,
            source_fingerprint=snapshot.source_fingerprint,
            created_at=utc_now(),
            selections=selections,
            result_content_sha256=sha256_bytes(result),
            diff_sha256=sha256_bytes(diff.encode("utf-8")),
        )
        return draft.model_copy(update={"plan_sha256": sealed_fingerprint(draft, "plan_sha256")})

    def verify(self) -> None:
        if self.plan_sha256 != sealed_fingerprint(self, "plan_sha256"):
            raise ValueError("MemoryPlan SHA-256 mismatch")


class MemoryVersionManifest(FrozenModel):
    schema_version: Literal[1] = 1
    backup_id: str
    source_id: str
    relative_path: str
    source_fingerprint: str
    content_sha256: str
    size_bytes: int = Field(ge=0)
    created_at: AwareDatetime
    version_path: str
    manifest_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(
            update={"manifest_sha256": sealed_fingerprint(self, "manifest_sha256")}
        )

    def verify(self) -> None:
        if self.manifest_sha256 != sealed_fingerprint(self, "manifest_sha256"):
            raise ValueError("MemoryVersionManifest SHA-256 mismatch")


class MemoryRestorePlan(FrozenModel):
    schema_version: Literal[1] = 1
    plan_id: str
    source_id: str
    source_path: str
    current_source_fingerprint: str
    backup_id: str
    backup_path: str
    backup_content_sha256: str
    created_at: AwareDatetime
    plan_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        snapshot: MemorySnapshot,
        manifest: MemoryVersionManifest,
    ) -> Self:
        manifest.verify()
        draft = cls(
            plan_id=str(uuid4()),
            source_id=snapshot.source_id,
            source_path=snapshot.relative_path,
            current_source_fingerprint=snapshot.source_fingerprint,
            backup_id=manifest.backup_id,
            backup_path=manifest.version_path,
            backup_content_sha256=manifest.content_sha256,
            created_at=utc_now(),
        )
        return draft.model_copy(update={"plan_sha256": sealed_fingerprint(draft, "plan_sha256")})

    def verify(self) -> None:
        if self.plan_sha256 != sealed_fingerprint(self, "plan_sha256"):
            raise ValueError("MemoryRestorePlan SHA-256 mismatch")


class MemoryApplyResult(FrozenModel):
    source_id: str
    plan_id: str
    backup_id: str
    content_sha256: str
    audit_event_sha256: str


class MemorySourceRegistry:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def list(self) -> tuple[MemorySource, ...]:
        path = self.paths.memory_sources_file
        if not path.exists():
            return ()
        document = MemorySourceRegistryDocument.model_validate_json(path.read_bytes())
        return document.sources

    def get(self, source_id: str) -> MemorySource:
        for source in self.list():
            if source.source_id == source_id:
                return source
        raise KeyError(f"unknown memory source: {source_id}")

    def find_by_path(self, path: Path) -> MemorySource | None:
        resolved = path.expanduser().resolve(strict=False)
        return next(
            (source for source in self.list() if source.path.resolve(strict=False) == resolved),
            None,
        )

    def register(
        self,
        *,
        file_path: Path,
        root_path: Path | None = None,
        allow_instruction_file: bool = False,
    ) -> MemorySource:
        source = MemorySource.create(
            root_path=root_path or file_path.parent,
            file_path=file_path,
            allow_instruction_file=allow_instruction_file,
        )
        sources = list(self.list())
        for existing in sources:
            if existing.source_id == source.source_id:
                return existing
            if existing.path.resolve(strict=False) == source.path.resolve(strict=False):
                raise ValueError("memory file is already registered under another root")
        sources.append(source)
        self._save(tuple(sorted(sources, key=lambda item: item.source_id)))
        return source

    def unregister(self, source_id: str) -> None:
        sources = self.list()
        remaining = tuple(source for source in sources if source.source_id != source_id)
        if len(remaining) == len(sources):
            raise KeyError(f"unknown memory source: {source_id}")
        self._save(remaining)

    def _save(self, sources: tuple[MemorySource, ...]) -> None:
        private_atomic_write(
            self.paths.memory_sources_file,
            canonical_json_bytes(MemorySourceRegistryDocument(sources=sources)),
        )


class MemoryPlanStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def path_for(self, plan: MemoryPlan | MemoryRestorePlan) -> Path:
        prefix = "memory-restore" if isinstance(plan, MemoryRestorePlan) else "memory"
        return self.paths.plans_dir / f"{prefix}-{plan.plan_id}.json"

    def save(self, plan: MemoryPlan | MemoryRestorePlan) -> Path:
        plan.verify()
        path = self.path_for(plan)
        data = canonical_json_bytes(plan)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("immutable memory plan already exists with different bytes")
            return path
        private_atomic_create(path, data)
        return path

    def load(self, path: Path) -> MemoryPlan:
        plan = MemoryPlan.model_validate_json(path.read_bytes())
        plan.verify()
        return plan

    def load_restore(self, path: Path) -> MemoryRestorePlan:
        plan = MemoryRestorePlan.model_validate_json(path.read_bytes())
        plan.verify()
        return plan


class MemoryService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.sources = MemorySourceRegistry(paths)
        self.plans = MemoryPlanStore(paths)

    def snapshot(self, source_id: str) -> MemorySnapshot:
        return read_memory_snapshot(self.sources.get(source_id))

    def create_plan(
        self,
        source_id: str,
        selections: tuple[MemorySelection, ...],
    ) -> tuple[MemoryPlan, str, Path]:
        snapshot = self.snapshot(source_id)
        plan = MemoryPlan.create(snapshot, selections)
        diff = memory_unified_diff(snapshot, render_memory(snapshot, selections))
        return plan, diff, self.plans.save(plan)

    def apply(self, plan: MemoryPlan, *, confirmation: str) -> MemoryApplyResult:
        plan.verify()
        if confirmation != plan.plan_id:
            raise ValueError("memory confirmation must equal the exact plan id")
        snapshot = self.snapshot(plan.source_id)
        if snapshot.relative_path != plan.source_path:
            raise ValueError("memory source path changed")
        if snapshot.source_fingerprint != plan.source_fingerprint:
            raise ValueError("memory source changed after plan creation")
        result = render_memory(snapshot, plan.selections)
        if sha256_bytes(result) != plan.result_content_sha256:
            raise ValueError("memory plan result SHA-256 mismatch")
        if result == snapshot.bytes:
            raise ValueError("memory plan contains no changes")

        manifest = self._create_version(snapshot)
        try:
            _atomic_replace_managed(snapshot, result)
            reread = self.snapshot(plan.source_id)
            if reread.content_sha256 != plan.result_content_sha256:
                raise RuntimeError("memory write verification failed")
        except BaseException:
            with contextlib.suppress(BaseException):
                _atomic_replace_unchecked(snapshot.path, snapshot.bytes, snapshot.mode)
            with AuditStore(self.paths) as audit:
                audit.append(
                    event_type="memory.apply",
                    actor="human",
                    result="failed",
                    plan_sha256=plan.plan_sha256,
                    target_ids=(plan.source_id,),
                    details={
                        "relative_path": plan.source_path,
                        "backup_id": manifest.backup_id,
                    },
                )
            raise

        with AuditStore(self.paths) as audit:
            event = audit.append(
                event_type="memory.apply",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=(plan.source_id,),
                details={
                    "relative_path": plan.source_path,
                    "backup_id": manifest.backup_id,
                    "backup_manifest_sha256": manifest.manifest_sha256,
                    "result_content_sha256": plan.result_content_sha256,
                    "diff_sha256": plan.diff_sha256,
                },
            )
        return MemoryApplyResult(
            source_id=plan.source_id,
            plan_id=plan.plan_id,
            backup_id=manifest.backup_id,
            content_sha256=plan.result_content_sha256,
            audit_event_sha256=event.event_sha256,
        )

    def history(self, source_id: str) -> tuple[MemoryVersionManifest, ...]:
        source = self.sources.get(source_id)
        directory = self.paths.memory_versions_dir / source.source_id
        manifests: list[MemoryVersionManifest] = []
        if not directory.exists():
            return ()
        root = directory.resolve(strict=True)
        for path in sorted(directory.glob("manifest-*.json")):
            if path.is_symlink() or path.resolve(strict=True).parent != root:
                raise ValueError("memory version manifest escaped its private directory")
            manifest = MemoryVersionManifest.model_validate_json(path.read_bytes())
            manifest.verify()
            if manifest.source_id != source_id:
                raise ValueError("memory version manifest belongs to another source")
            version_path = Path(manifest.version_path)
            if version_path.is_symlink() or version_path.resolve(strict=True).parent != root:
                raise ValueError("memory version data escaped its private directory")
            data = version_path.read_bytes()
            if sha256_bytes(data) != manifest.content_sha256 or len(data) != manifest.size_bytes:
                raise ValueError("memory version data no longer matches its manifest")
            manifests.append(manifest)
        return tuple(sorted(manifests, key=lambda item: item.created_at, reverse=True))

    def create_restore_plan(
        self,
        source_id: str,
        backup_id: str,
    ) -> tuple[MemoryRestorePlan, Path]:
        snapshot = self.snapshot(source_id)
        manifest = next(
            (item for item in self.history(source_id) if item.backup_id == backup_id),
            None,
        )
        if manifest is None:
            raise KeyError(f"unknown memory backup: {backup_id}")
        plan = MemoryRestorePlan.create(snapshot=snapshot, manifest=manifest)
        return plan, self.plans.save(plan)

    def apply_restore(
        self,
        plan: MemoryRestorePlan,
        *,
        confirmation: str,
    ) -> MemoryApplyResult:
        plan.verify()
        if confirmation != plan.plan_id:
            raise ValueError("memory restore confirmation must equal the exact plan id")
        snapshot = self.snapshot(plan.source_id)
        if snapshot.relative_path != plan.source_path:
            raise ValueError("memory source path changed")
        if snapshot.source_fingerprint != plan.current_source_fingerprint:
            raise ValueError("memory source changed after restore plan creation")
        backup_path = Path(plan.backup_path)
        version_root = (self.paths.memory_versions_dir / plan.source_id).resolve(strict=True)
        if (
            backup_path.is_symlink()
            or not backup_path.is_file()
            or backup_path.resolve(strict=True).parent != version_root
        ):
            raise ValueError("memory restore backup is unavailable")
        backup = backup_path.read_bytes()
        if sha256_bytes(backup) != plan.backup_content_sha256:
            raise ValueError("memory restore backup SHA-256 mismatch")
        safety_backup = self._create_version(snapshot)
        try:
            _atomic_replace_managed(snapshot, backup)
            reread = self.snapshot(plan.source_id)
            if reread.content_sha256 != plan.backup_content_sha256:
                raise RuntimeError("memory restore verification failed")
        except BaseException:
            with contextlib.suppress(BaseException):
                _atomic_replace_unchecked(snapshot.path, snapshot.bytes, snapshot.mode)
            raise
        with AuditStore(self.paths) as audit:
            event = audit.append(
                event_type="memory.restore",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=(plan.source_id,),
                details={
                    "relative_path": plan.source_path,
                    "restored_backup_id": plan.backup_id,
                    "safety_backup_id": safety_backup.backup_id,
                    "result_content_sha256": plan.backup_content_sha256,
                },
            )
        return MemoryApplyResult(
            source_id=plan.source_id,
            plan_id=plan.plan_id,
            backup_id=safety_backup.backup_id,
            content_sha256=plan.backup_content_sha256,
            audit_event_sha256=event.event_sha256,
        )

    def _create_version(self, snapshot: MemorySnapshot) -> MemoryVersionManifest:
        directory = self.paths.memory_versions_dir / snapshot.source_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            directory.chmod(0o700)
        backup_id = str(uuid4())
        version_path = directory / f"version-{backup_id}.bin"
        manifest_path = directory / f"manifest-{backup_id}.json"
        private_atomic_create(version_path, snapshot.bytes)
        stored = version_path.read_bytes()
        if stored != snapshot.bytes:
            raise RuntimeError("memory version verification failed")
        manifest = MemoryVersionManifest(
            backup_id=backup_id,
            source_id=snapshot.source_id,
            relative_path=snapshot.relative_path,
            source_fingerprint=snapshot.source_fingerprint,
            content_sha256=snapshot.content_sha256,
            size_bytes=snapshot.size_bytes,
            created_at=utc_now(),
            version_path=str(version_path),
        ).seal()
        private_atomic_create(manifest_path, canonical_json_bytes(manifest))
        return manifest


def validate_memory_path(
    root_path: Path,
    file_path: Path,
    *,
    allow_instruction_file: bool,
) -> tuple[Path, Path]:
    root_lexical = root_path.expanduser().absolute()
    target_lexical = file_path.expanduser().absolute()
    if root_lexical.is_symlink():
        raise ValueError("memory root must not be a symbolic link")
    root = root_lexical.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("memory root must be a directory")
    try:
        relative = target_lexical.relative_to(root_lexical)
    except ValueError as exc:
        raise ValueError("memory file is outside its registered root") from exc
    current = root_lexical
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("memory path must not contain symbolic links")
    target = target_lexical.resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("memory file escaped its registered root") from exc
    if not target.is_file():
        raise ValueError("memory source must be a regular file")
    if target.suffix.casefold() not in SUPPORTED_MEMORY_SUFFIXES:
        raise ValueError("memory source must be a Markdown or text file")
    if target.name.casefold() in INSTRUCTION_FILENAMES and not allow_instruction_file:
        raise ValueError("instruction files require --allow-instruction-file")
    return root, target


def read_memory_snapshot(source: MemorySource) -> MemorySnapshot:
    root, target = validate_memory_path(
        Path(source.root_path),
        source.path,
        allow_instruction_file=source.allow_instruction_file,
    )
    stat = target.stat()
    if stat.st_size > MAX_MEMORY_FILE_BYTES:
        raise ValueError("memory file exceeds the 5 MiB MVP limit")
    raw = target.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("memory file must be valid UTF-8") from exc
    newline = _dominant_newline(text)
    segments = segment_memory_text(
        text,
        relative_path=source.relative_path,
        byte_offset=3 if bom else 0,
    )
    return MemorySnapshot(
        source_id=source.source_id,
        root_path=str(root),
        relative_path=target.relative_to(root).as_posix(),
        content_sha256=sha256_bytes(raw),
        size_bytes=len(raw),
        mtime_ns=stat.st_mtime_ns,
        inode=stat.st_ino,
        mode=stat.st_mode & 0o777,
        utf8_bom=bom,
        newline=newline,
        segments=segments,
        captured_at=utc_now(),
    )


def segment_memory_text(
    text: str,
    *,
    relative_path: str,
    byte_offset: int = 0,
) -> tuple[MemorySegment, ...]:
    if not text:
        return ()
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [text]
    byte_positions = [byte_offset]
    for line in lines:
        byte_positions.append(byte_positions[-1] + len(line.encode("utf-8")))

    segments: list[MemorySegment] = []
    headings: list[str] = []
    index = 0
    if lines and lines[0].strip() == "---":
        closing = next(
            (
                candidate
                for candidate in range(1, len(lines))
                if lines[candidate].strip() in {"---", "..."}
            ),
            None,
        )
        if closing is not None:
            _append_segment(
                segments,
                lines,
                0,
                closing + 1,
                byte_positions,
                relative_path,
                (),
                MemorySegmentKind.FRONT_MATTER,
                protected=True,
                reason="YAML front matter is protected in the MVP",
            )
            index = closing + 1

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            end = index + 1
            while end < len(lines) and not lines[end].strip():
                end += 1
            _append_segment(
                segments,
                lines,
                index,
                end,
                byte_positions,
                relative_path,
                tuple(headings),
                MemorySegmentKind.WHITESPACE,
                protected=True,
                reason="structural whitespace is preserved",
            )
            index = end
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            headings = [title] if level == 1 else [*(headings[:1]), title]
            _append_segment(
                segments,
                lines,
                index,
                index + 1,
                byte_positions,
                relative_path,
                tuple(headings),
                MemorySegmentKind.HEADING,
                protected=True,
                reason="Markdown headings are protected in the MVP",
            )
            index += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            end = index + 1
            while end < len(lines):
                if lines[end].lstrip().startswith(marker):
                    end += 1
                    break
                end += 1
            _append_segment(
                segments,
                lines,
                index,
                end,
                byte_positions,
                relative_path,
                tuple(headings),
                MemorySegmentKind.CODE_BLOCK,
                protected=True,
                reason="fenced code blocks are protected in the MVP",
            )
            index = end
            continue

        list_match = _LIST_RE.match(line)
        if list_match:
            indentation = len(list_match.group(1).replace("\t", "    "))
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if (
                    not candidate.strip()
                    or _HEADING_RE.match(candidate)
                    or _FENCE_RE.match(candidate)
                ):
                    break
                next_list = _LIST_RE.match(candidate)
                if next_list:
                    next_indent = len(next_list.group(1).replace("\t", "    "))
                    if next_indent <= indentation:
                        break
                if candidate[:1] not in {" ", "\t"} and next_list is None:
                    break
                end += 1
            _append_segment(
                segments,
                lines,
                index,
                end,
                byte_positions,
                relative_path,
                tuple(headings),
                MemorySegmentKind.LIST_ITEM,
            )
            index = end
            continue

        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if (
                not candidate.strip()
                or _HEADING_RE.match(candidate)
                or _FENCE_RE.match(candidate)
                or _LIST_RE.match(candidate)
            ):
                break
            end += 1
        _append_segment(
            segments,
            lines,
            index,
            end,
            byte_positions,
            relative_path,
            tuple(headings),
            MemorySegmentKind.PARAGRAPH,
        )
        index = end
    return tuple(segments)


def validate_memory_selections(
    snapshot: MemorySnapshot,
    selections: tuple[MemorySelection, ...],
) -> None:
    by_id = {segment.segment_id: segment for segment in snapshot.segments}
    seen: set[str] = set()
    for selection in selections:
        if selection.segment_id in seen:
            raise ValueError("memory selections contain duplicate segment ids")
        seen.add(selection.segment_id)
        segment = by_id.get(selection.segment_id)
        if segment is None:
            raise ValueError(f"unknown memory segment: {selection.segment_id}")
        if segment.protected and selection.action in {
            MemoryAction.DELETE,
            MemoryAction.REPLACE,
        }:
            raise ValueError(f"protected memory segment cannot be changed: {selection.segment_id}")


def render_memory(
    snapshot: MemorySnapshot,
    selections: tuple[MemorySelection, ...],
) -> bytes:
    validate_memory_selections(snapshot, selections)
    selected = {selection.segment_id: selection for selection in selections}
    parts: list[str] = []
    for segment in snapshot.segments:
        selection = selected.get(segment.segment_id)
        action = selection.action if selection is not None else MemoryAction.KEEP
        if action in {MemoryAction.KEEP, MemoryAction.PROTECT}:
            parts.append(segment.text)
        elif action is MemoryAction.REPLACE:
            assert selection is not None and selection.replacement is not None
            replacement = _normalize_newlines(selection.replacement, snapshot.newline)
            if _ends_with_newline(segment.text) and not _ends_with_newline(replacement):
                replacement += snapshot.newline
            parts.append(replacement)
    body = "".join(parts).encode("utf-8")
    return (b"\xef\xbb\xbf" if snapshot.utf8_bom else b"") + body


def memory_unified_diff(snapshot: MemorySnapshot, result: bytes) -> str:
    before = snapshot.bytes.decode("utf-8-sig")
    after = result.decode("utf-8-sig")
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{snapshot.relative_path}",
            tofile=f"b/{snapshot.relative_path}",
        )
    )


def _append_segment(
    output: list[MemorySegment],
    lines: list[str],
    start: int,
    end: int,
    byte_positions: list[int],
    relative_path: str,
    heading_path: tuple[str, ...],
    kind: MemorySegmentKind,
    *,
    protected: bool = False,
    reason: str | None = None,
) -> None:
    text = "".join(lines[start:end])
    start_byte = byte_positions[start]
    end_byte = byte_positions[end]
    content_sha256 = sha256_bytes(text.encode("utf-8"))
    segment_id = sha256_bytes(
        (
            "csm-memory-segment-v1\0"
            + relative_path
            + "\0"
            + "/".join(heading_path)
            + f"\0{start_byte}\0{end_byte}\0{content_sha256}"
        ).encode("utf-8")
    )
    output.append(
        MemorySegment(
            segment_id=segment_id,
            kind=kind,
            heading_path=heading_path,
            start_byte=start_byte,
            end_byte=end_byte,
            text=text,
            content_sha256=content_sha256,
            protected=protected,
            protection_reason=reason,
        )
    )


def _dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf >= lf and crlf >= cr and crlf:
        return "\r\n"
    if cr > lf and cr:
        return "\r"
    return "\n"


def _normalize_newlines(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def _ends_with_newline(text: str) -> bool:
    return text.endswith(("\n", "\r"))


def _atomic_replace_managed(snapshot: MemorySnapshot, data: bytes) -> None:
    source = MemorySource(
        source_id=snapshot.source_id,
        root_path=snapshot.root_path,
        relative_path=snapshot.relative_path,
        created_at=snapshot.captured_at,
        allow_instruction_file=snapshot.path.name.casefold() in INSTRUCTION_FILENAMES,
    )
    current = read_memory_snapshot(source)
    if current.source_fingerprint != snapshot.source_fingerprint:
        raise ValueError("memory source changed immediately before write")
    _atomic_replace_unchecked(snapshot.path, data, snapshot.mode)


def _atomic_replace_unchecked(path: Path, data: bytes, mode: int) -> None:
    if path.is_symlink():
        raise ValueError("refusing to replace a memory symlink")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode or 0o600)
        if path.is_symlink():
            raise ValueError("memory path became a symlink before replacement")
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
