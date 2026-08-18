from __future__ import annotations

from pathlib import Path

import pytest

from codex_session_manager.memory import (
    MemoryAction,
    MemoryPlan,
    MemorySelection,
    MemoryService,
    MemorySourceRegistry,
    memory_unified_diff,
    render_memory,
)


def _memory_source(tmp_path: Path, app_paths):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("# Profile\n\nLikes tea.\n\n- Uses macOS\n", encoding="utf-8")
    source = MemorySourceRegistry(app_paths).register(file_path=target, root_path=root)
    return source, target


def test_memory_plan_builds_exact_diff_and_rejects_protected_changes(
    tmp_path: Path, app_paths
) -> None:
    source, _target = _memory_source(tmp_path, app_paths)
    snapshot = MemoryService(app_paths).snapshot(source.source_id)
    paragraph = next(segment for segment in snapshot.segments if "Likes tea" in segment.text)
    heading = next(segment for segment in snapshot.segments if segment.text.startswith("# "))
    selection = MemorySelection(
        segment_id=paragraph.segment_id,
        action=MemoryAction.REPLACE,
        replacement="Likes green tea.",
        reason="user correction",
    )

    plan = MemoryPlan.create(snapshot, (selection,))
    result = render_memory(snapshot, plan.selections)
    diff = memory_unified_diff(snapshot, result)

    plan.verify()
    assert b"Likes green tea.\n" in result
    assert "-Likes tea." in diff
    assert "+Likes green tea." in diff

    with pytest.raises(ValueError, match="protected"):
        MemoryPlan.create(
            snapshot,
            (
                MemorySelection(
                    segment_id=heading.segment_id,
                    action=MemoryAction.DELETE,
                ),
            ),
        )


def test_memory_plan_rejects_unknown_and_duplicate_segments(tmp_path: Path, app_paths) -> None:
    source, _target = _memory_source(tmp_path, app_paths)
    snapshot = MemoryService(app_paths).snapshot(source.source_id)
    paragraph = next(segment for segment in snapshot.segments if "Likes tea" in segment.text)

    with pytest.raises(ValueError, match="unknown"):
        MemoryPlan.create(
            snapshot,
            (MemorySelection(segment_id="missing", action=MemoryAction.DELETE),),
        )
    with pytest.raises(ValueError, match="duplicate"):
        MemoryPlan.create(
            snapshot,
            (
                MemorySelection(segment_id=paragraph.segment_id, action=MemoryAction.KEEP),
                MemorySelection(segment_id=paragraph.segment_id, action=MemoryAction.DELETE),
            ),
        )
