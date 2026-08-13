"""Human-approved App Server protocol profiles.

The bundled inventory is descriptive evidence, not an automatic migration
mechanism.  If it is missing or malformed the write allowlist becomes empty,
which keeps every App Server mutation fail-closed.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Any, Final

LOGGER = logging.getLogger(__name__)
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProtocolProfile:
    """One reviewed Codex version and exact generated-schema combination."""

    codex_version: str
    schema_sha256: str
    stable_methods: frozenset[str]
    experimental_methods: frozenset[str]
    critical_fields: Mapping[str, bool]


def _string_set(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    result = frozenset(value)
    if len(result) != len(value):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _load_profiles() -> dict[tuple[str, str], ProtocolProfile]:
    resource = resources.files("codex_session_manager").joinpath("protocol_profiles.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported protocol profile schema")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError("protocol profiles must be an array")
    profiles: dict[tuple[str, str], ProtocolProfile] = {}
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            raise ValueError("protocol profile must be an object")
        version = raw.get("codex_version")
        digest = raw.get("schema_sha256")
        if not isinstance(version, str) or not version:
            raise ValueError("protocol profile lacks codex_version")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise ValueError("protocol profile has invalid schema_sha256")
        stable = _string_set(raw.get("stable_methods"), "stable_methods")
        experimental = _string_set(raw.get("experimental_methods"), "experimental_methods")
        if stable & experimental:
            raise ValueError("stable and experimental methods must be disjoint")
        fields = raw.get("critical_fields")
        if not isinstance(fields, dict) or any(
            not isinstance(name, str) or not isinstance(present, bool)
            for name, present in fields.items()
        ):
            raise ValueError("critical_fields must map names to booleans")
        key = (version, digest)
        if key in profiles:
            raise ValueError("duplicate protocol profile")
        profiles[key] = ProtocolProfile(
            codex_version=version,
            schema_sha256=digest,
            stable_methods=stable,
            experimental_methods=experimental,
            critical_fields=MappingProxyType(dict(sorted(fields.items()))),
        )
    return profiles


try:
    _loaded_profiles = _load_profiles()
except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
    LOGGER.error("unable to load audited App Server protocol profiles: %s", exc)
    _loaded_profiles = {}

AUDITED_PROTOCOL_PROFILES: Final[Mapping[tuple[str, str], ProtocolProfile]] = MappingProxyType(
    _loaded_profiles
)

TRUSTED_WRITE_SCHEMAS: Final[frozenset[tuple[str, str]]] = frozenset(AUDITED_PROTOCOL_PROFILES)


def nearest_profile(codex_version: str | None) -> ProtocolProfile | None:
    """Return a same-version baseline, or the newest bundled profile."""

    same_version = [
        profile
        for profile in AUDITED_PROTOCOL_PROFILES.values()
        if profile.codex_version == codex_version
    ]
    if same_version:
        return sorted(same_version, key=lambda item: item.schema_sha256)[-1]
    if not AUDITED_PROTOCOL_PROFILES:
        return None
    return sorted(
        AUDITED_PROTOCOL_PROFILES.values(),
        key=lambda item: (item.codex_version, item.schema_sha256),
    )[-1]
