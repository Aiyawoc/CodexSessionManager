from pathlib import Path

import pytest

import codex_session_manager.config as config
from codex_session_manager.config import codex_binary, get_paths, private_atomic_create


def test_codex_home_honors_official_environment(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "official-codex-home"
    monkeypatch.delenv("CSM_CODEX_HOME", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(root))

    assert get_paths().codex_home == root.resolve()


def test_codex_home_rejects_conflicting_account_roots(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CSM_CODEX_HOME", str(tmp_path / "account-a"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "account-b"))

    with pytest.raises(ValueError, match="different Codex data roots"):
        get_paths()


def test_codex_binary_honors_desktop_cli_path_after_explicit_override(
    monkeypatch, tmp_path: Path
) -> None:
    cli = tmp_path / "codex"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o700)
    monkeypatch.delenv("CSM_CODEX_BIN", raising=False)
    monkeypatch.setenv("CODEX_CLI_PATH", str(cli))
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setattr(config, "_bundled_codex_binary", lambda: None, raising=False)

    assert codex_binary() == str(cli)


def test_codex_binary_uses_bundled_codex_when_desktop_path_is_empty(monkeypatch) -> None:
    bundled = "/Applications/ChatGPT.app/Contents/Resources/codex"
    monkeypatch.delenv("CSM_CODEX_BIN", raising=False)
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setattr(config, "_bundled_codex_binary", lambda: bundled, raising=False)

    assert codex_binary() == bundled


def test_codex_binary_prefers_bundled_codex_over_path_codex(monkeypatch) -> None:
    bundled = "/Applications/ChatGPT.app/Contents/Resources/codex"
    monkeypatch.delenv("CSM_CODEX_BIN", raising=False)
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(config, "_bundled_codex_binary", lambda: bundled, raising=False)

    assert codex_binary() == bundled


def test_private_atomic_create_never_replaces_existing_evidence(tmp_path: Path) -> None:
    destination = tmp_path / "evidence.json"
    private_atomic_create(destination, b"first")

    with pytest.raises(FileExistsError):
        private_atomic_create(destination, b"second")
    assert destination.read_bytes() == b"first"
    assert not tuple(tmp_path.glob(".*.tmp"))
