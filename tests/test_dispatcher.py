from __future__ import annotations

import io

from codex_session_manager.dispatcher import _configure_windows_stdio


def test_windows_stdio_is_reconfigured_to_utf8() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")

    _configure_windows_stdio(platform="win32", streams=(stream,))
    stream.write("中文")
    stream.flush()

    assert stream.encoding.lower().replace("-", "") == "utf8"
    assert raw.getvalue() == "中文".encode()


def test_non_windows_stdio_is_unchanged() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")

    _configure_windows_stdio(platform="darwin", streams=(stream,))

    assert stream.encoding.lower() == "cp1252"
