"""Streaming age-encrypted ``.csmbackup`` creation and verification."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import tarfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Literal, Protocol, Self
from uuid import uuid4

import ijson

from codex_session_manager.app_server import SubprocessAppServer
from codex_session_manager.audit import AuditStore
from codex_session_manager.config import AppPaths, bundled_age_path, bundled_resources_root
from codex_session_manager.hashing import canonical_json_bytes, hash_file, hash_stream, utc_now
from codex_session_manager.inventory import normalize_thread
from codex_session_manager.models import (
    BackupEntry,
    BackupManifest,
    BackupVerification,
    ItemKind,
    ThreadSnapshot,
)
from codex_session_manager.version import __version__

EXPECTED_AGE_VERSION = "1.3.1"
MANIFEST_PATH = "manifest.json"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_BACKUP_ENTRIES = 10_000
MAX_LOGICAL_MEMBER_BYTES = 512 * 1024 * 1024
MAX_BACKUP_MEMBER_BYTES = 16 * 1024 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 256 * 1024 * 1024 * 1024


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EncryptionSpec:
    mode: Literal["age-recipient", "age-passphrase"]
    recipient: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "age-recipient" and not (self.recipient or "").strip():
            raise ValueError("recipient mode requires an age recipient")
        if self.mode == "age-passphrase" and self.recipient is not None:
            raise ValueError("passphrase mode does not accept a recipient")


@dataclass(frozen=True, slots=True)
class DecryptionSpec:
    identity_file: Path | None = None
    passphrase: bool = False

    def __post_init__(self) -> None:
        if self.identity_file is not None and self.passphrase:
            raise ValueError("choose identity or terminal passphrase, not both")


class EncryptionSession(Protocol):
    stream: IO[bytes]

    def finish(self) -> None: ...

    def abort(self) -> None: ...


class CipherBackend(Protocol):
    def open_encrypt(self, destination: Path, spec: EncryptionSpec) -> EncryptionSession: ...

    def open_decrypt(
        self, source: Path, spec: DecryptionSpec
    ) -> contextlib.AbstractContextManager[IO[bytes]]: ...


class _AgeEncryptionSession:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        if process.stdin is None:
            raise BackupError("age encryption stdin is unavailable")
        self.stream = process.stdin
        self._finished = False

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.stream.close()
        status = self.process.wait()
        if status != 0:
            raise BackupError(f"age encryption failed with exit status {status}")

    def abort(self) -> None:
        if self._finished:
            return
        self._finished = True
        with contextlib.suppress(OSError):
            self.stream.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)


class AgeBackend:
    """Invoke a preinstalled or bundle-local official age binary."""

    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable or bundled_age_path()
        if self.executable is None:
            raise BackupError("age executable is unavailable; run csm doctor or install the .app")
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise BackupError(f"age executable is not runnable: {self.executable}")
        try:
            version = self.version()
        except (OSError, subprocess.SubprocessError) as exc:
            raise BackupError(f"cannot verify age executable: {self.executable}") from exc
        if version not in {EXPECTED_AGE_VERSION, f"v{EXPECTED_AGE_VERSION}"}:
            raise BackupError(
                f"unsupported age version {version!r}; expected v{EXPECTED_AGE_VERSION}"
            )
        resources = bundled_resources_root()
        if resources is not None:
            expected_path = (resources / "bin" / ("age.exe" if os.name == "nt" else "age")).resolve(
                strict=False
            )
            if self.executable.resolve(strict=False) != expected_path:
                raise BackupError("packaged runtime must use the bundle-local age executable")
            verification_path = resources / "licenses" / "age-verification.json"
            try:
                verification = json.loads(verification_path.read_text(encoding="utf-8"))
                expected_digest = verification["binary_sha256"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise BackupError("bundle-local age verification metadata is invalid") from exc
            digest, _size = hash_file(self.executable)
            if not isinstance(expected_digest, str) or digest != expected_digest:
                raise BackupError("bundle-local age executable SHA-256 mismatch")

    def version(self) -> str:
        completed = subprocess.run(
            [str(self.executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip()

    def open_encrypt(self, destination: Path, spec: EncryptionSpec) -> EncryptionSession:
        command = [str(self.executable)]
        if spec.mode == "age-recipient":
            command.extend(["--recipient", str(spec.recipient)])
        else:
            # age reads the passphrase directly from the controlling terminal.
            # CSM never receives it and therefore cannot log or expose it.
            command.append("--passphrase")
        command.extend(["--output", str(destination)])
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        return _AgeEncryptionSession(process)

    @contextlib.contextmanager
    def open_decrypt(self, source: Path, spec: DecryptionSpec) -> Iterator[IO[bytes]]:
        command = [str(self.executable), "--decrypt"]
        if spec.identity_file is not None:
            command.extend(["--identity", str(spec.identity_file)])
        command.append(str(source))
        process = subprocess.Popen(command, stdout=subprocess.PIPE)
        if process.stdout is None:
            raise BackupError("age decryption stdout is unavailable")
        try:
            yield process.stdout
            process.stdout.close()
            status = process.wait()
            if status != 0:
                raise BackupError(f"age decryption failed with exit status {status}")
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            raise


class _IteratorReader(io.RawIOBase):
    """Expose fresh byte chunks as a tarfile-compatible readable object."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        super().__init__()
        self._chunks = iter(chunks)
        self._buffer = bytearray()
        self._done = False

    def readable(self) -> bool:
        return True

    def readinto(self, target: Any) -> int:
        if self._done and not self._buffer:
            return 0
        while len(self._buffer) < len(target) and not self._done:
            try:
                self._buffer.extend(next(self._chunks))
            except StopIteration:
                self._done = True
        count = min(len(target), len(self._buffer))
        target[:count] = self._buffer[:count]
        del self._buffer[:count]
        return count


class _HashingReader:
    """Hash and count every byte consumed by a streaming JSON parser."""

    def __init__(self, source: IO[bytes]) -> None:
        self.source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


def _logical_provenance(stream: IO[bytes]) -> tuple[str, int, dict[str, str]]:
    """Validate one bounded member and recompute its embedded snapshot binding."""

    tracker = _HashingReader(stream)
    try:
        records = ijson.items(tracker, "")
        record = next(records)
        try:
            next(records)
        except StopIteration:
            pass
        else:
            raise BackupError("logical backup entry contains multiple JSON roots")
    except StopIteration as exc:
        raise BackupError("logical backup entry is empty") from exc
    except (ijson.JSONError, ValueError) as exc:
        raise BackupError("logical backup entry is not valid streaming JSON") from exc
    if not isinstance(record, Mapping):
        raise BackupError("logical backup entry must be a JSON object")
    if set(record) != {"schema_version", "source", "thread"}:
        raise BackupError("logical backup entry contains unexpected top-level fields")
    if record.get("schema_version") != 1:
        raise BackupError("unsupported logical backup schema version")
    source = record.get("source")
    thread_value = record.get("thread")
    if not isinstance(source, Mapping) or not isinstance(thread_value, Mapping):
        raise BackupError("logical backup entry lacks source or thread data")
    if set(source) != {"type", "thread_id", "snapshot_fingerprint"} or not all(
        isinstance(source.get(key), str) for key in ("type", "thread_id", "snapshot_fingerprint")
    ):
        raise BackupError("logical backup source binding is malformed")
    try:
        thread = ThreadSnapshot.model_validate(thread_value)
    except ValueError as exc:
        raise BackupError("logical backup entry contains an invalid thread snapshot") from exc
    values = {
        "thread_id": str(source.get("thread_id") or ""),
        "snapshot_fingerprint": str(source.get("snapshot_fingerprint") or ""),
        "source_type": str(source.get("type") or ""),
        "embedded_thread_id": thread.id,
        "embedded_snapshot_fingerprint": thread.backup_fingerprint,
    }
    return tracker.digest.hexdigest(), tracker.size, values


def _json_chunks(value: Any) -> Iterator[bytes]:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for fragment in encoder.iterencode(value):
        yield fragment.encode("utf-8")


def _hash_chunks(factory: Callable[[], Iterable[bytes]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in factory():
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


@dataclass(frozen=True, slots=True)
class BundleSource:
    archive_path: str
    kind: Literal["logical", "raw", "attachment", "sidecar"]
    thread_id: str | None
    size: int
    sha256: str
    open_stream: Callable[[], contextlib.AbstractContextManager[IO[bytes]]]
    postcheck: Callable[[], None] | None = None

    @classmethod
    def from_json(
        cls,
        archive_path: str,
        value: Any,
        *,
        kind: Literal["logical", "sidecar"],
        thread_id: str | None,
    ) -> Self:
        def factory() -> Iterable[bytes]:
            return _json_chunks(value)

        sha256, size = _hash_chunks(factory)

        @contextlib.contextmanager
        def open_json() -> Iterator[IO[bytes]]:
            stream = io.BufferedReader(_IteratorReader(factory()))
            try:
                yield stream
            finally:
                stream.close()

        return cls(archive_path, kind, thread_id, size, sha256, open_json)

    @classmethod
    def from_file(
        cls,
        archive_path: str,
        path: Path,
        *,
        kind: Literal["raw", "attachment"],
        thread_id: str | None,
    ) -> Self:
        if path.is_symlink():
            raise BackupError(f"backup source must not be a symbolic link: {path}")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise BackupError(f"backup source is not a regular file: {path}")
        before = resolved.stat()
        sha256, size = hash_file(resolved)

        @contextlib.contextmanager
        def open_file() -> Iterator[IO[bytes]]:
            with resolved.open("rb") as stream:
                yield stream

        def postcheck() -> None:
            after = resolved.stat()
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if identity_before != identity_after:
                raise BackupError(f"source changed while backing up: {resolved}")

        return cls(archive_path, kind, thread_id, size, sha256, open_file, postcheck)


def _safe_archive_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise BackupError(f"unsafe archive path: {value!r}")
    normalized = str(path)
    if normalized == MANIFEST_PATH:
        raise BackupError("bundle source cannot shadow manifest.json")
    return normalized


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def _ensure_under(path: Path, roots: tuple[Path, ...]) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or resolved.is_symlink():
        raise BackupError(f"symbolic links are not backup sources: {path}")
    for root in roots:
        resolved_root = root.resolve(strict=False)
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError:
            continue
        current = resolved_root
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise BackupError(f"symbolic-link escape rejected: {path}")
        return resolved
    raise BackupError(f"path is outside approved attachment/raw roots: {path}")


class BackupWriter:
    def __init__(self, backend: CipherBackend) -> None:
        self.backend = backend

    def create(
        self,
        destination: Path,
        *,
        sources: tuple[BundleSource, ...],
        source_fingerprints: dict[str, str],
        encryption: EncryptionSpec,
        notes: tuple[str, ...] = (),
    ) -> BackupManifest:
        if destination.suffix != ".csmbackup":
            raise BackupError("backup destination must end in .csmbackup")
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.encrypted.tmp")
        seen_paths: set[str] = set()
        entries: list[BackupEntry] = []
        if len(sources) > MAX_BACKUP_ENTRIES:
            raise BackupError("backup exceeds the member-count safety limit")
        total_size = 0
        for source in sources:
            safe_path = _safe_archive_path(source.archive_path)
            if safe_path in seen_paths:
                raise BackupError(f"duplicate bundle path: {safe_path}")
            seen_paths.add(safe_path)
            if source.size > MAX_BACKUP_MEMBER_BYTES:
                raise BackupError(f"backup member exceeds the size safety limit: {safe_path}")
            if source.kind == "logical" and source.size > MAX_LOGICAL_MEMBER_BYTES:
                raise BackupError(f"logical backup member exceeds the parsing limit: {safe_path}")
            total_size += source.size
            if total_size > MAX_BACKUP_TOTAL_BYTES:
                raise BackupError("backup exceeds the total-size safety limit")
            entries.append(
                BackupEntry(
                    path=safe_path,
                    kind=source.kind,
                    size=source.size,
                    sha256=source.sha256,
                    thread_id=source.thread_id,
                )
            )
        manifest = BackupManifest(
            backup_id=str(uuid4()),
            created_at=utc_now(),
            tool_version=__version__,
            encryption=encryption.mode,
            entries=tuple(entries),
            source_fingerprints=source_fingerprints,
            notes=notes,
        ).seal()
        manifest.verify()
        session = self.backend.open_encrypt(temporary, encryption)
        published = False
        try:
            with tarfile.open(fileobj=session.stream, mode="w|") as archive:
                for source, entry in zip(sources, entries, strict=True):
                    with source.open_stream() as stream:
                        archive.addfile(_tar_info(entry.path, entry.size), fileobj=stream)
                    if source.postcheck:
                        source.postcheck()
                manifest_bytes = canonical_json_bytes(manifest)
                archive.addfile(
                    _tar_info(MANIFEST_PATH, len(manifest_bytes)),
                    fileobj=io.BytesIO(manifest_bytes),
                )
            session.finish()
            # Windows rejects fsync on a read-only descriptor. Reopen the
            # completed encrypted file without truncation but with write access.
            with temporary.open("rb+") as encrypted:
                os.fsync(encrypted.fileno())
            with contextlib.suppress(OSError):
                temporary.chmod(0o600)
            # Publish without an overwrite race. Hard-linking beside the final
            # path is atomic and fails if another process created it meanwhile.
            os.link(temporary, destination)
            published = True
            with contextlib.suppress(OSError):
                temporary.unlink()
            with contextlib.suppress(OSError):
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return manifest
        except BaseException:
            session.abort()
            if temporary.exists() and not published:
                temporary.unlink()
            raise


class BackupReader:
    def __init__(self, backend: CipherBackend) -> None:
        self.backend = backend

    def verify(self, source: Path, *, decryption: DecryptionSpec) -> BackupVerification:
        if source.is_symlink():
            raise BackupError("backup verification refuses symbolic links")
        if not source.is_file():
            raise FileNotFoundError(source)
        resolved_source = source.resolve(strict=True)
        ciphertext_before = hash_file(resolved_source)
        observed: dict[str, tuple[str, int]] = {}
        logical_provenance: dict[str, dict[str, str]] = {}
        observed_total = 0
        manifest: BackupManifest | None = None
        manifest_seen = False
        with (
            self.backend.open_decrypt(resolved_source, decryption) as decrypted,
            tarfile.open(fileobj=decrypted, mode="r|*") as archive,
        ):
            for member in archive:
                if manifest_seen:
                    raise BackupError("manifest.json must be the final archive member")
                if not member.isfile():
                    raise BackupError(f"unsupported tar member type: {member.name}")
                safe_name = _safe_member_path(member.name)
                if member.size > MAX_BACKUP_MEMBER_BYTES:
                    raise BackupError(
                        f"archive member exceeds the size safety limit: {member.name}"
                    )
                if safe_name != MANIFEST_PATH:
                    observed_total += member.size
                    if observed_total > MAX_BACKUP_TOTAL_BYTES:
                        raise BackupError("backup exceeds the total-size safety limit")
                if safe_name != MANIFEST_PATH and len(observed) >= MAX_BACKUP_ENTRIES:
                    raise BackupError("backup exceeds the member-count safety limit")
                if safe_name.startswith("logical/") and member.size > MAX_LOGICAL_MEMBER_BYTES:
                    raise BackupError(
                        f"logical backup member exceeds the parsing limit: {member.name}"
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise BackupError(f"cannot read archive member: {safe_name}")
                if safe_name == MANIFEST_PATH:
                    manifest_seen = True
                    if member.size > MAX_MANIFEST_BYTES:
                        raise BackupError("manifest.json exceeds the safety limit")
                    data = stream.read(MAX_MANIFEST_BYTES + 1)
                    if len(data) != member.size:
                        raise BackupError("manifest.json was truncated")
                    manifest = BackupManifest.model_validate_json(data)
                    manifest.verify()
                else:
                    if safe_name.startswith("logical/"):
                        digest, size, provenance = _logical_provenance(stream)
                        logical_provenance[safe_name] = provenance
                    else:
                        digest, size = hash_stream(stream)
                    if safe_name in observed:
                        raise BackupError(f"duplicate tar member: {safe_name}")
                    observed[safe_name] = (digest, size)
        if manifest is None:
            raise BackupError("backup lacks final manifest.json")
        expected = {entry.path: (entry.sha256, entry.size) for entry in manifest.entries}
        if observed != expected:
            missing = sorted(set(expected) - set(observed))
            extra = sorted(set(observed) - set(expected))
            mismatched = sorted(
                path for path in set(expected) & set(observed) if expected[path] != observed[path]
            )
            raise BackupError(
                f"backup checksum mismatch; missing={missing}, extra={extra}, mismatched={mismatched}"
            )
        embedded_source_fingerprints: dict[str, str] = {}
        for entry in manifest.entries:
            if entry.kind != "logical":
                continue
            entry_provenance = logical_provenance.get(entry.path)
            source_fingerprint = manifest.source_fingerprints.get(entry.thread_id or "")
            embedded_fingerprint = (
                entry_provenance.get("embedded_snapshot_fingerprint")
                if entry_provenance is not None
                else None
            )
            if (
                entry_provenance is None
                or entry_provenance.get("source_type") != "codex-app-server"
                or entry_provenance.get("thread_id") != entry.thread_id
                or entry_provenance.get("embedded_thread_id") != entry.thread_id
                or entry_provenance.get("snapshot_fingerprint") != source_fingerprint
                or embedded_fingerprint != source_fingerprint
            ):
                raise BackupError(f"logical recovery provenance mismatch: {entry.path}")
            assert entry.thread_id is not None
            assert isinstance(embedded_fingerprint, str)
            embedded_source_fingerprints[entry.thread_id] = embedded_fingerprint
        ciphertext_after = hash_file(resolved_source)
        if ciphertext_after != ciphertext_before:
            raise BackupError("backup ciphertext changed during verification")
        return BackupVerification(
            manifest=manifest,
            embedded_source_fingerprints=embedded_source_fingerprints,
            ciphertext_sha256=ciphertext_after[0],
            ciphertext_size=ciphertext_after[1],
        )

    def iter_logical_json(
        self,
        source: Path,
        *,
        decryption: DecryptionSpec,
        verified_manifest: BackupManifest,
    ) -> Iterator[tuple[BackupEntry, Any]]:
        """Decrypt a second time and yield verified logical records one by one."""

        verified_manifest.verify()
        expected = {entry.path: entry for entry in verified_manifest.entries}
        seen: set[str] = set()
        manifest_seen = False
        with (
            self.backend.open_decrypt(source, decryption) as decrypted,
            tarfile.open(fileobj=decrypted, mode="r|*") as archive,
        ):
            for member in archive:
                if not member.isfile():
                    raise BackupError(f"unsupported second-pass tar member: {member.name}")
                name = _safe_member_path(member.name)
                if manifest_seen:
                    raise BackupError("second pass found a member after manifest.json")
                if name == MANIFEST_PATH:
                    manifest_seen = True
                    if member.size > MAX_MANIFEST_BYTES:
                        raise BackupError("second-pass manifest exceeds the safety limit")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise BackupError("cannot read second-pass manifest")
                    data = stream.read(MAX_MANIFEST_BYTES + 1)
                    if len(data) != member.size:
                        raise BackupError("second-pass manifest was truncated")
                    second_manifest = BackupManifest.model_validate_json(data)
                    second_manifest.verify()
                    if second_manifest.manifest_sha256 != verified_manifest.manifest_sha256:
                        raise BackupError("backup manifest changed between verification passes")
                    continue
                entry = expected.get(name)
                if entry is None:
                    raise BackupError(f"second pass found unexpected member: {name}")
                if name in seen:
                    raise BackupError(f"second pass found duplicate member: {name}")
                seen.add(name)
                stream = archive.extractfile(member)
                if stream is None:
                    raise BackupError(f"cannot read second-pass member: {name}")
                if entry.kind not in {"logical", "sidecar"}:
                    # Raw rollout restoration is intentionally disabled.
                    digest, size = hash_stream(stream)
                    if (digest, size) != (entry.sha256, entry.size):
                        raise BackupError(f"second-pass checksum mismatch: {name}")
                    continue
                data = stream.read(entry.size + 1)
                if len(data) != entry.size:
                    raise BackupError(f"second-pass size mismatch: {name}")
                digest = hashlib.sha256(data).hexdigest()
                if digest != entry.sha256:
                    raise BackupError(f"second-pass checksum mismatch: {name}")
                try:
                    value = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise BackupError(f"second-pass JSON is invalid: {name}") from exc
                yield entry, value
        if not manifest_seen:
            raise BackupError("second pass lacks final manifest.json")
        if seen != set(expected):
            missing = sorted(set(expected) - seen)
            raise BackupError(f"second pass is missing verified members: {missing}")


def _safe_member_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise BackupError(f"unsafe tar member path: {value!r}")
    return str(path)


def _tool_sidecar(raw_thread: Mapping[str, Any]) -> list[dict[str, Any]]:
    sidecar: list[dict[str, Any]] = []
    turns = raw_thread.get("turns")
    if not isinstance(turns, list):
        return sidecar
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        turn_id = turn.get("id")
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            normalized = normalize_thread(
                {"id": "sidecar-probe", "turns": [{"id": str(turn_id), "items": [dict(item)]}]}
            )
            kind = normalized.turns[0].items[0].kind
            if kind in {
                ItemKind.TOOL_CALL,
                ItemKind.TOOL_RESULT,
                ItemKind.FILE_CHANGE,
                ItemKind.VERIFICATION,
            }:
                sidecar.append({"turn_id": turn_id, "item": dict(item), "inert": True})
    return sidecar


class BackupService:
    """Build and verify backups from App Server snapshots."""

    def __init__(
        self,
        *,
        client: SubprocessAppServer,
        paths: AppPaths,
        backend: CipherBackend,
        audit: AuditStore | None = None,
    ) -> None:
        self.client = client
        self.paths = paths
        self.backend = backend
        self.audit = audit

    def create(
        self,
        destination: Path,
        *,
        snapshots: tuple[ThreadSnapshot, ...],
        encryption: EncryptionSpec,
        verification_decryption: DecryptionSpec,
        include_raw: bool = True,
        attachments: tuple[Path, ...] = (),
    ) -> BackupManifest:
        if not snapshots:
            raise BackupError("at least one thread is required")
        incomplete = [
            snapshot.id
            for snapshot in snapshots
            if not snapshot.content_complete or not snapshot.mapping_complete
        ]
        if incomplete:
            raise BackupError(
                "backup requires complete content and lineage mapping for: "
                + ", ".join(sorted(incomplete))
            )
        approved_raw_roots = (
            self.paths.codex_home / "sessions",
            self.paths.codex_home / "archived_sessions",
        )
        approved_attachment_roots = (
            self.paths.codex_home / "attachments",
            self.paths.codex_home / "artifacts",
        )
        sources: list[BundleSource] = []
        source_fingerprints: dict[str, str] = {}
        for snapshot in snapshots:
            raw_thread = self.client.read_thread(snapshot.id, include_turns=True)
            logical = normalize_thread(
                raw_thread,
                archived=snapshot.archived,
                content_complete=True,
            )
            logical = logical.model_copy(
                update={
                    "title": logical.title or snapshot.title,
                    "preview": logical.preview or snapshot.preview,
                    "cwd": logical.cwd or snapshot.cwd,
                    "git_remote": logical.git_remote or snapshot.git_remote,
                    "source_kind": (
                        logical.source_kind
                        if logical.source_kind != "unknown"
                        else snapshot.source_kind
                    ),
                    "model_provider": logical.model_provider or snapshot.model_provider,
                    "created_at": logical.created_at or snapshot.created_at,
                    "updated_at": logical.updated_at or snapshot.updated_at,
                    "pinned": snapshot.pinned,
                    "ephemeral": snapshot.ephemeral,
                    "parent_id": logical.parent_id or snapshot.parent_id,
                    "session_id": logical.session_id or snapshot.session_id,
                    "forked_from_id": logical.forked_from_id or snapshot.forked_from_id,
                    "spawned_descendant_ids": snapshot.spawned_descendant_ids,
                    "size_bytes": logical.size_bytes or snapshot.size_bytes,
                    "raw_path": logical.raw_path or snapshot.raw_path,
                    "mapping_complete": snapshot.mapping_complete,
                }
            )
            if logical.backup_fingerprint != snapshot.backup_fingerprint:
                raise BackupError(f"thread changed while preparing backup: {snapshot.id}")
            source_fingerprints[snapshot.id] = logical.backup_fingerprint
            record = {
                "schema_version": 1,
                "source": {
                    "type": "codex-app-server",
                    "thread_id": snapshot.id,
                    "snapshot_fingerprint": logical.backup_fingerprint,
                },
                "thread": logical.model_dump(mode="json"),
            }
            sources.append(
                BundleSource.from_json(
                    f"logical/threads/{snapshot.id}.json",
                    record,
                    kind="logical",
                    thread_id=snapshot.id,
                )
            )
            sidecar = _tool_sidecar(raw_thread)
            if sidecar:
                sources.append(
                    BundleSource.from_json(
                        f"sidecars/{snapshot.id}/tools.json",
                        {"schema_version": 1, "items": sidecar, "execute": False},
                        kind="sidecar",
                        thread_id=snapshot.id,
                    )
                )
            if include_raw and logical.raw_path:
                raw_path = _ensure_under(Path(logical.raw_path), approved_raw_roots)
                sources.append(
                    BundleSource.from_file(
                        f"raw/{snapshot.id}.jsonl",
                        raw_path,
                        kind="raw",
                        thread_id=snapshot.id,
                    )
                )
        for attachment in attachments:
            resolved = _ensure_under(attachment, approved_attachment_roots)
            relative_root = next(
                root
                for root in approved_attachment_roots
                if resolved.is_relative_to(root.resolve(strict=False))
            )
            relative = resolved.relative_to(relative_root.resolve(strict=False))
            sources.append(
                BundleSource.from_file(
                    f"attachments/{relative.as_posix()}",
                    resolved,
                    kind="attachment",
                    thread_id=None,
                )
            )
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        candidate = destination.with_name(f".{destination.name}.{uuid4().hex}.candidate.csmbackup")
        writer = BackupWriter(self.backend)
        try:
            manifest = writer.create(
                candidate,
                sources=tuple(sources),
                source_fingerprints=source_fingerprints,
                encryption=encryption,
                notes=(
                    "raw rollouts are disaster-recovery preservation only; "
                    "V1 raw restore is disabled",
                ),
            )
            verification = BackupReader(self.backend).verify(
                candidate,
                decryption=verification_decryption,
            )
            verified = verification.manifest
            if verified.manifest_sha256 != manifest.manifest_sha256:
                raise BackupError("post-create verification returned a different manifest")
            os.link(candidate, destination)
            with contextlib.suppress(OSError):
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            if self.audit:
                self.audit.record_verified_backup(verification, destination)
                self.audit.append(
                    event_type="backup.verify",
                    actor="human",
                    result="succeeded",
                    target_ids=tuple(sorted(verified.source_fingerprints)),
                    details={
                        "manifest_sha256": verified.manifest_sha256,
                        "entry_count": len(verified.entries),
                    },
                )
            return verified
        finally:
            with contextlib.suppress(FileNotFoundError):
                candidate.unlink()
