from __future__ import annotations

import os
from pathlib import Path

import pytest

from codex_session_manager.memory import (
    MemorySegmentKind,
    MemorySourceRegistry,
    read_memory_snapshot,
)


def test_registered_memory_snapshot_preserves_bom_crlf_and_all_bytes(
    tmp_path: Path, app_paths
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "MEMORY.md"
    original = (
        b"\xef\xbb\xbf---\r\nprivate: true\r\n---\r\n\r\n"
        b"# Profile\r\n\r\n- Likes tea\r\n- Uses macOS\r\n\r\nA final paragraph.\r\n"
    )
    target.write_bytes(original)

    registry = MemorySourceRegistry(app_paths)
    source = registry.register(file_path=target, root_path=root)
    snapshot = read_memory_snapshot(source)

    assert registry.get(source.source_id) == source
    assert snapshot.bytes == original
    assert snapshot.utf8_bom
    assert snapshot.newline == "\r\n"
    assert {segment.kind for segment in snapshot.segments} >= {
        MemorySegmentKind.FRONT_MATTER,
        MemorySegmentKind.HEADING,
        MemorySegmentKind.LIST_ITEM,
        MemorySegmentKind.PARAGRAPH,
        MemorySegmentKind.WHITESPACE,
    }
    assert snapshot.segments[0].protected
    assert all(
        left.end_byte == right.start_byte
        for left, right in zip(snapshot.segments, snapshot.segments[1:], strict=False)
    )


def test_memory_registry_rejects_escape_symlink_and_instruction_file(
    tmp_path: Path, app_paths
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    registry = MemorySourceRegistry(app_paths)

    with pytest.raises(ValueError, match="outside"):
        registry.register(file_path=outside, root_path=root)

    link = root / "linked.md"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symbolic links are unavailable on this platform")
    with pytest.raises(ValueError, match="symbolic links"):
        registry.register(file_path=link, root_path=root)

    instructions = root / "AGENTS.md"
    instructions.write_text("# Instructions\n", encoding="utf-8")
    with pytest.raises(ValueError, match="instruction files"):
        registry.register(file_path=instructions, root_path=root)
    registered = registry.register(
        file_path=instructions,
        root_path=root,
        allow_instruction_file=True,
    )
    assert registered.allow_instruction_file
