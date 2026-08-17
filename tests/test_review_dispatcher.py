from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from codex_session_manager import dispatcher


def _fake_gui(monkeypatch: Any, run_gui: Any) -> None:
    module = ModuleType("codex_session_manager.gui.main")
    module.run_gui = run_gui  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "codex_session_manager.gui.main", module)


def test_dispatcher_routes_sealed_review_request(monkeypatch: Any, tmp_path: Path) -> None:
    request_path = tmp_path / "review.json"
    called: dict[str, object] = {}

    def run_gui(*, request_path: Path | None = None, thread_id: str | None = None) -> int:
        called["request_path"] = request_path
        called["thread_id"] = thread_id
        return 7

    _fake_gui(monkeypatch, run_gui)
    monkeypatch.setattr(sys, "argv", ["CodexSessionManager", "--request", str(request_path)])

    assert dispatcher.main() == 7
    assert called == {"request_path": request_path, "thread_id": None}


def test_dispatcher_reports_invalid_review_request(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    request_path = tmp_path / "review.json"

    def run_gui(*, request_path: Path | None = None, thread_id: str | None = None) -> int:
        raise ValueError("request failed validation")

    _fake_gui(monkeypatch, run_gui)
    monkeypatch.setattr(sys, "argv", ["CodexSessionManager", "--request", str(request_path)])

    assert dispatcher.main() == 2
    assert "无法打开审查请求" in capsys.readouterr().err
