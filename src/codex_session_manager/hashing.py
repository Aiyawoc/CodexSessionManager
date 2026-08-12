"""Deterministic serialization and SHA-256 helpers.

Plans and manifests use these functions as their integrity boundary.  The
serializer deliberately rejects unknown values instead of falling back to
``repr`` because a process-dependent representation would make drift checks
unreliable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import IO, Any

from pydantic import BaseModel


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _normalize(value: Any) -> Any:
    """Convert supported objects to a canonical JSON-compatible tree."""

    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python", exclude_none=False))
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetimes cannot be hashed")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON keys must be strings: {type(key)!r}")
            normalized[key] = _normalize(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized_items = [_normalize(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats cannot be hashed")
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value)!r}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* using stable UTF-8 JSON."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 hex digest."""

    return hashlib.sha256(value).hexdigest()


def fingerprint(value: Any) -> str:
    """Hash a canonical JSON value."""

    return sha256_bytes(canonical_json_bytes(value))


def sealed_fingerprint(model: BaseModel, hash_field: str) -> str:
    """Hash a model after replacing its own seal with an empty string."""

    payload = model.model_dump(mode="python", exclude_none=False)
    if hash_field not in payload:
        raise ValueError(f"missing seal field: {hash_field}")
    payload[hash_field] = ""
    return fingerprint(payload)


def hash_stream(stream: IO[bytes], chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    """Hash a binary stream from its current position and return digest and size."""

    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    """Hash a regular file without following a symlink at the final component."""

    if path.is_symlink():
        raise ValueError(f"refusing to hash symlink: {path}")
    with path.open("rb") as stream:
        return hash_stream(stream, chunk_size)


def hash_chunks(chunks: Iterable[bytes]) -> tuple[str, int]:
    """Hash an iterable of byte chunks."""

    digest = hashlib.sha256()
    size = 0
    for chunk in chunks:
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def estimate_tokens(text: str) -> int:
    """Return a conservative, local-only token estimate for UI planning."""

    if not text:
        return 0
    utf8_len = len(text.encode("utf-8"))
    return max(1, math.ceil(utf8_len / 3.2))
