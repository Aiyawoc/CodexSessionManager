from __future__ import annotations

import contextlib
import io
import os
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pytest

from codex_session_manager.backup import (
    BackupError,
    BackupReader,
    BackupService,
    BackupWriter,
    BundleSource,
    DecryptionSpec,
    EncryptionSpec,
)
from codex_session_manager.inventory import normalize_thread
from codex_session_manager.models import BackupManifest


class _PlainSession:
    def __init__(self, destination: Path) -> None:
        self.stream: IO[bytes] = destination.open("wb")

    def finish(self) -> None:
        self.stream.flush()
        self.stream.close()

    def abort(self) -> None:
        self.stream.close()


class _TestCipher:
    """Test-only transport; production has no plaintext backend."""

    def open_encrypt(self, destination: Path, _spec: EncryptionSpec) -> _PlainSession:
        return _PlainSession(destination)

    @contextlib.contextmanager
    def open_decrypt(self, source: Path, _spec: DecryptionSpec) -> Iterator[IO[bytes]]:
        with source.open("rb") as stream:
            yield stream


class _ChangingCipher:
    def __init__(self, first: Path, second: Path) -> None:
        self.paths = iter((first, second))

    @contextlib.contextmanager
    def open_decrypt(self, _source: Path, _spec: DecryptionSpec) -> Iterator[IO[bytes]]:
        with next(self.paths).open("rb") as stream:
            yield stream


class _MutatingCipher(_TestCipher):
    @contextlib.contextmanager
    def open_decrypt(self, source: Path, _spec: DecryptionSpec) -> Iterator[IO[bytes]]:
        with source.open("rb") as stream:
            yield stream
        source.write_bytes(source.read_bytes() + b"changed-after-decryption")


def _create_backup(path: Path):
    snapshot = normalize_thread(
        {
            "id": "thread-1",
            "name": "Thread one",
            "preview": "hello world",
            "status": {"type": "idle"},
            "turns": [
                {
                    "id": "turn-1",
                    "status": "completed",
                    "items": [
                        {
                            "id": "message-1",
                            "type": "agentMessage",
                            "role": "assistant",
                            "text": "hello world",
                        }
                    ],
                }
            ],
        },
        content_complete=True,
    )
    source_fingerprint = snapshot.backup_fingerprint
    source = BundleSource.from_json(
        "logical/threads/thread-1.json",
        {
            "schema_version": 1,
            "source": {
                "type": "codex-app-server",
                "thread_id": "thread-1",
                "snapshot_fingerprint": source_fingerprint,
            },
            "thread": snapshot.model_dump(mode="json"),
        },
        kind="logical",
        thread_id="thread-1",
    )
    return BackupWriter(_TestCipher()).create(
        path,
        sources=(source,),
        source_fingerprints={"thread-1": source_fingerprint},
        encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
    )


def test_streaming_backup_manifest_is_final_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "sample.csmbackup"
    created = _create_backup(path)
    verification = BackupReader(_TestCipher()).verify(path, decryption=DecryptionSpec())
    assert verification.manifest.manifest_sha256 == created.manifest_sha256
    assert verification.ciphertext_size == path.stat().st_size
    assert len(verification.ciphertext_sha256) == 64
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(path, "r:") as archive:
        assert archive.getnames()[-1] == "manifest.json"


def test_backup_refuses_to_replace_existing_destination(tmp_path: Path) -> None:
    path = tmp_path / "existing.csmbackup"
    original = b"existing encrypted evidence"
    path.write_bytes(original)

    with pytest.raises(FileExistsError):
        _create_backup(path)
    assert path.read_bytes() == original


def test_backup_detects_payload_tampering(tmp_path: Path) -> None:
    path = tmp_path / "tampered.csmbackup"
    _create_backup(path)
    data = bytearray(path.read_bytes())
    offset = data.find(b"world")
    assert offset >= 0
    data[offset] ^= 1
    path.write_bytes(data)
    with pytest.raises(BackupError, match="checksum mismatch"):
        BackupReader(_TestCipher()).verify(path, decryption=DecryptionSpec())


def test_backup_detects_ciphertext_replacement_during_verification(tmp_path: Path) -> None:
    path = tmp_path / "changing.csmbackup"
    _create_backup(path)

    with pytest.raises(BackupError, match="changed during verification"):
        BackupReader(_MutatingCipher()).verify(path, decryption=DecryptionSpec())


def test_backup_rejects_unsafe_member_and_manifest_shadow(tmp_path: Path) -> None:
    unsafe = BundleSource.from_json(
        "../escape.json",
        {},
        kind="logical",
        thread_id="thread-1",
    )
    with pytest.raises(BackupError, match="unsafe archive path"):
        BackupWriter(_TestCipher()).create(
            tmp_path / "unsafe.csmbackup",
            sources=(unsafe,),
            source_fingerprints={"thread-1": "f" * 64},
            encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
        )
    shadow = BundleSource.from_json("manifest.json", {}, kind="logical", thread_id="thread-1")
    with pytest.raises(BackupError, match="shadow"):
        BackupWriter(_TestCipher()).create(
            tmp_path / "shadow.csmbackup",
            sources=(shadow,),
            source_fingerprints={"thread-1": "f" * 64},
            encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
        )


def test_backup_rejects_symbolic_link_source(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"secret")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    with pytest.raises(BackupError, match="symbolic link"):
        BundleSource.from_file("raw/thread.jsonl", link, kind="raw", thread_id="thread")


def test_reader_rejects_member_after_manifest(tmp_path: Path) -> None:
    path = tmp_path / "bad-order.csmbackup"
    with tarfile.open(path, "w:") as archive:
        manifest = io.BytesIO(b"{}")
        info = tarfile.TarInfo("manifest.json")
        info.size = 2
        archive.addfile(info, manifest)
        extra = io.BytesIO(b"x")
        info = tarfile.TarInfo("logical/extra.json")
        info.size = 1
        archive.addfile(info, extra)
    with pytest.raises((BackupError, ValueError)):
        BackupReader(_TestCipher()).verify(path, decryption=DecryptionSpec())


def test_manifest_rejects_self_reported_coverage_without_logical_entry() -> None:
    manifest = BackupManifest(
        backup_id="self-reported",
        created_at="2026-08-11T00:00:00Z",
        tool_version="test",
        encryption="age-recipient",
        entries=(),
        source_fingerprints={"victim": "f" * 64},
    ).seal()
    with pytest.raises(ValueError, match="logical thread entries exactly"):
        manifest.verify()


def test_restore_second_pass_requires_every_verified_member(tmp_path: Path) -> None:
    complete = tmp_path / "complete.csmbackup"
    _create_backup(complete)
    manifest_only = tmp_path / "manifest-only.csmbackup"
    with tarfile.open(complete, "r:") as source_archive:
        manifest_bytes = source_archive.extractfile("manifest.json").read()  # type: ignore[union-attr]
    with tarfile.open(manifest_only, "w:") as destination_archive:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        destination_archive.addfile(info, io.BytesIO(manifest_bytes))

    reader = BackupReader(_ChangingCipher(complete, manifest_only))
    verification = reader.verify(complete, decryption=DecryptionSpec())
    with pytest.raises(BackupError, match="missing verified members"):
        tuple(
            reader.iter_logical_json(
                complete,
                decryption=DecryptionSpec(),
                verified_manifest=verification.manifest,
            )
        )


def test_reader_recomputes_embedded_snapshot_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "self-reported.csmbackup"
    real = normalize_thread(
        {"id": "thread-1", "preview": "real", "turns": []}, content_complete=True
    )
    forged = real.model_copy(update={"preview": "forged recovery content"})
    source = BundleSource.from_json(
        "logical/threads/thread-1.json",
        {
            "schema_version": 1,
            "source": {
                "type": "codex-app-server",
                "thread_id": "thread-1",
                "snapshot_fingerprint": real.backup_fingerprint,
            },
            "thread": forged.model_dump(mode="json"),
        },
        kind="logical",
        thread_id="thread-1",
    )
    BackupWriter(_TestCipher()).create(
        path,
        sources=(source,),
        source_fingerprints={"thread-1": real.backup_fingerprint},
        encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
    )

    with pytest.raises(BackupError, match="logical recovery provenance mismatch"):
        BackupReader(_TestCipher()).verify(path, decryption=DecryptionSpec())


def test_backup_service_binds_reread_logical_snapshot(tmp_path: Path, app_paths) -> None:
    raw_thread = {
        "id": "thread-1",
        "name": "Thread one",
        "cwd": "/tmp/project",
        "status": {"type": "idle"},
        "turns": [
            {
                "id": "turn-1",
                "status": "completed",
                "items": [
                    {
                        "id": "message-1",
                        "type": "agentMessage",
                        "role": "assistant",
                        "text": "recoverable content",
                    }
                ],
            }
        ],
    }
    snapshot = normalize_thread(raw_thread, content_complete=True)

    class Client:
        def read_thread(self, thread_id: str, *, include_turns: bool = False):
            assert thread_id == "thread-1"
            assert include_turns
            return raw_thread

    destination = tmp_path / "service.csmbackup"
    manifest = BackupService(
        client=Client(),  # type: ignore[arg-type]
        paths=app_paths,
        backend=_TestCipher(),
    ).create(
        destination,
        snapshots=(snapshot,),
        encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
        verification_decryption=DecryptionSpec(),
        include_raw=False,
    )

    assert manifest.source_fingerprints == {"thread-1": snapshot.backup_fingerprint}


def test_backup_service_does_not_publish_before_full_verification(
    tmp_path: Path, app_paths, monkeypatch
) -> None:
    raw_thread = {
        "id": "thread-1",
        "status": {"type": "idle"},
        "turns": [{"id": "turn-1", "items": []}],
    }
    snapshot = normalize_thread(raw_thread, content_complete=True)

    class Client:
        def read_thread(self, thread_id: str, *, include_turns: bool = False):
            assert thread_id == snapshot.id
            assert include_turns
            return raw_thread

    def reject_verification(*_args, **_kwargs):
        raise BackupError("verification failed")

    monkeypatch.setattr(BackupReader, "verify", reject_verification)
    destination = tmp_path / "unverified.csmbackup"

    with pytest.raises(BackupError, match="verification failed"):
        BackupService(
            client=Client(),  # type: ignore[arg-type]
            paths=app_paths,
            backend=_TestCipher(),
        ).create(
            destination,
            snapshots=(snapshot,),
            encryption=EncryptionSpec(mode="age-recipient", recipient="age1test"),
            verification_decryption=DecryptionSpec(),
            include_raw=False,
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".*.candidate.csmbackup"))
