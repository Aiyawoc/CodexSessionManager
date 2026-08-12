"""Runtime and bundle diagnostics shared by source and packaged modes."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QLibraryInfo, qVersion

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.backup import EXPECTED_AGE_VERSION, AgeBackend
from codex_session_manager.config import AppPaths, app_bundle_root, bundled_age_path
from codex_session_manager.hashing import hash_file

EXPECTED_PYTHON = (3, 13, 14)
EXPECTED_PYSIDE = "6.11.1"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "required": self.required,
        }


def _writable_directory(path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = path / f".doctor-{os.getpid()}"
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        probe.unlink()
        return Check(f"write:{path}", True, "writable")
    except OSError as exc:
        return Check(f"write:{path}", False, str(exc))


def _qt_plugin_directory(reported: Path, bundle: Path | None) -> Path:
    """Resolve Qt's plugin directory in source and Nuitka bundle layouts."""

    candidates = [reported]
    if bundle is not None:
        candidates.extend(
            (
                bundle / "MacOS" / "PySide6" / "qt-plugins",
                bundle / "MacOS" / "PySide6" / "Qt" / "plugins",
            )
        )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return reported


def run_doctor(paths: AppPaths, *, probe_app_server: bool = True) -> dict[str, Any]:
    bundle = app_bundle_root()
    checks: list[Check] = []
    current_python = sys.version_info[:3]
    checks.append(
        Check(
            "python",
            current_python == EXPECTED_PYTHON,
            f"{platform.python_implementation()} {platform.python_version()} at {sys.executable}",
        )
    )
    checks.append(
        Check("architecture", platform.machine() == "arm64", platform.machine(), required=False)
    )
    checks.append(Check("PySide6", pyside_version == EXPECTED_PYSIDE, pyside_version))
    checks.append(Check("Qt", qVersion() == EXPECTED_PYSIDE, qVersion()))
    reported_plugin_path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    plugin_path = _qt_plugin_directory(reported_plugin_path, bundle)
    checks.append(Check("Qt plugins", plugin_path.is_dir(), str(plugin_path)))
    platform_plugin = plugin_path / "platforms" / "libqcocoa.dylib"
    checks.append(Check("Qt cocoa plugin", platform_plugin.is_file(), str(platform_plugin)))
    image_formats = plugin_path / "imageformats"
    checks.append(Check("Qt image plugins", image_formats.is_dir(), str(image_formats)))
    age_path = bundled_age_path()
    if age_path is None:
        checks.append(Check("age", False, "not found"))
    else:
        try:
            version = AgeBackend(age_path).version()
            expected = version in {EXPECTED_AGE_VERSION, f"v{EXPECTED_AGE_VERSION}"}
            checks.append(Check("age", expected, f"{version} at {age_path}"))
        except (OSError, RuntimeError) as exc:
            checks.append(Check("age", False, str(exc)))
        verification_path = (
            bundle / "Resources" / "licenses" / "age-verification.json"
            if bundle
            else age_path.parent / "verification.json"
        )
        try:
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            expected_sha = verification.get("binary_sha256")
            actual_sha, _ = hash_file(age_path)
            integrity_ok = isinstance(expected_sha, str) and actual_sha == expected_sha
            checks.append(
                Check(
                    "age integrity",
                    integrity_ok,
                    f"sha256={actual_sha}; metadata={verification_path}",
                )
            )
        except (OSError, ValueError, TypeError) as exc:
            checks.append(Check("age integrity", False, str(exc)))
    if bundle:
        checks.append(Check("standalone bundle", True, str(bundle)))
        checks.append(Check("uv not required", True, "packaged runtime", required=False))
    else:
        uv = shutil.which("uv")
        checks.append(Check("development uv", uv is not None, uv or "not found"))
    for directory in (paths.data_dir, paths.config_dir, paths.cache_dir, paths.log_dir):
        checks.append(_writable_directory(directory))
    capability_data: dict[str, Any] | None = None
    if probe_app_server:
        try:
            client, capabilities = connect_and_probe(request_timeout=20)
            try:
                capability_data = capabilities.model_dump(mode="json") | {
                    "fingerprint": capabilities.fingerprint,
                    "write_enabled": capabilities.write_enabled,
                }
                checks.append(
                    Check(
                        "Codex App Server",
                        capabilities.schema_complete,
                        capabilities.read_only_reason
                        or f"codex {capabilities.codex_version}; exact schema established",
                    )
                )
                checks.append(
                    Check(
                        "Codex App Server writes",
                        capabilities.write_enabled,
                        (
                            "audited schema allowlist matched"
                            if capabilities.write_enabled
                            else capabilities.read_only_reason or "write capability unavailable"
                        ),
                        required=False,
                    )
                )
            finally:
                client.close()
        except (OSError, RuntimeError) as exc:
            checks.append(Check("Codex App Server", False, str(exc)))
    required_ok = all(check.ok for check in checks if check.required)
    return {
        "ok": required_ok,
        "mode": "standalone-app" if bundle else "development",
        "checks": [check.as_dict() for check in checks],
        "capabilities": capability_data,
    }
