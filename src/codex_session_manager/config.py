"""Runtime paths and bundle resource discovery."""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "CodexSessionManager"
APP_AUTHOR = "CodexSessionManager"


def _override(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    log_dir: Path
    plans_dir: Path
    imports_dir: Path
    backups_dir: Path
    audit_db: Path
    codex_home: Path

    def ensure(self) -> None:
        """Create application-owned directories with user-only permissions."""

        for path in (
            self.data_dir,
            self.config_dir,
            self.cache_dir,
            self.log_dir,
            self.plans_dir,
            self.imports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                path.chmod(0o700)


def get_paths() -> AppPaths:
    """Resolve platform-native paths and one unambiguous Codex account root."""

    dirs = PlatformDirs(APP_NAME, APP_AUTHOR, roaming=False)
    data_dir = _override("CSM_DATA_DIR") or Path(dirs.user_data_dir)
    config_dir = _override("CSM_CONFIG_DIR") or Path(dirs.user_config_dir)
    cache_dir = _override("CSM_CACHE_DIR") or Path(dirs.user_cache_dir)
    log_dir = _override("CSM_LOG_DIR") or Path(dirs.user_log_dir)
    csm_codex_home = _override("CSM_CODEX_HOME")
    official_codex_home = _override("CODEX_HOME")
    if (
        csm_codex_home is not None
        and official_codex_home is not None
        and csm_codex_home.resolve(strict=False) != official_codex_home.resolve(strict=False)
    ):
        raise ValueError("CSM_CODEX_HOME and CODEX_HOME refer to different Codex data roots")
    codex_home = (csm_codex_home or official_codex_home or Path.home() / ".codex").resolve(
        strict=False
    )
    return AppPaths(
        data_dir=data_dir,
        config_dir=config_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
        plans_dir=data_dir / "plans",
        imports_dir=data_dir / "imports",
        backups_dir=data_dir / "backups",
        audit_db=data_dir / "audit.sqlite3",
        codex_home=codex_home,
    )


def app_bundle_root() -> Path | None:
    """Return ``Contents`` when running inside a macOS application bundle."""

    executable = Path(sys.executable).resolve()
    if executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
        return executable.parent.parent
    return None


def standalone_root() -> Path | None:
    """Return the platform-native root of an installed standalone build."""

    bundle = app_bundle_root()
    if bundle is not None:
        return bundle
    executable_root = Path(sys.executable).resolve().parent
    if (executable_root / "Resources" / "build-channel").is_file():
        return executable_root
    return None


def bundled_resources_root() -> Path | None:
    """Locate resources in either a macOS app bundle or Windows dist folder."""

    root = standalone_root()
    return root / "Resources" if root is not None else None


def bundled_age_path(*, allow_development_path: bool = True) -> Path | None:
    """Locate the bundled age executable without downloading anything."""

    resources = bundled_resources_root()
    if resources:
        candidate = resources / "bin" / ("age.exe" if os.name == "nt" else "age")
        return candidate if candidate.is_file() else None
    if allow_development_path:
        explicit = _override("CSM_AGE_BIN")
        if explicit:
            return explicit
        repository_candidate = (
            Path(__file__).parents[2] / "vendor" / "age" / ("age.exe" if os.name == "nt" else "age")
        )
        if repository_candidate.is_file():
            return repository_candidate
        system_age = shutil.which("age")
        if system_age:
            return Path(system_age)
    return None


def codex_binary() -> str:
    """Return the configured Codex CLI path."""

    return os.environ.get("CSM_CODEX_BIN", "codex")


def stable_installed_app() -> Path:
    """Return the user-level stable application root used by hooks."""

    explicit = _override("CSM_APP_PATH")
    if explicit is not None:
        return explicit
    if os.name == "nt":
        local_app_data = _override("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return local_app_data / APP_NAME
    return Path.home() / "Applications" / "CodexSessionManager.app"


def stable_app_executable() -> Path:
    installed = stable_installed_app()
    if os.name == "nt":
        return installed if installed.suffix.casefold() == ".exe" else installed / f"{APP_NAME}.exe"
    return installed / "Contents" / "MacOS" / APP_NAME


def private_atomic_write(path: Path, data: bytes) -> None:
    """Atomically write user-private data beside the final destination."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
