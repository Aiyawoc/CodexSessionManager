from pathlib import Path

import pytest

from codex_session_manager.config import get_paths


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
