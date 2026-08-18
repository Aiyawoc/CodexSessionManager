from __future__ import annotations

from pathlib import Path

import pytest

from codex_session_manager.audit import AuditStore
from codex_session_manager.memory import (
    MemoryAction,
    MemorySelection,
    MemoryService,
    MemorySourceRegistry,
)


def _prepared_memory(tmp_path: Path, app_paths):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("# Memory\n\nOld preference.\n", encoding="utf-8")
    source = MemorySourceRegistry(app_paths).register(file_path=target, root_path=root)
    service = MemoryService(app_paths)
    snapshot = service.snapshot(source.source_id)
    paragraph = next(segment for segment in snapshot.segments if "Old preference" in segment.text)
    plan, diff, plan_path = service.create_plan(
        source.source_id,
        (
            MemorySelection(
                segment_id=paragraph.segment_id,
                action=MemoryAction.REPLACE,
                replacement="New preference.",
            ),
        ),
    )
    return service, source, target, plan, diff, plan_path


def test_memory_apply_creates_verified_version_and_audit(tmp_path: Path, app_paths) -> None:
    service, source, target, plan, diff, plan_path = _prepared_memory(tmp_path, app_paths)

    result = service.apply(plan, confirmation=plan.plan_id)

    assert plan_path.is_file()
    assert "New preference." in target.read_text(encoding="utf-8")
    assert "+New preference." in diff
    history = service.history(source.source_id)
    assert len(history) == 1
    assert Path(history[0].version_path).read_text(encoding="utf-8").endswith("Old preference.\n")
    with AuditStore(app_paths) as audit:
        audit.verify_chain()
        event = next(audit.iter_events(limit=1))
    assert event.event_type == "memory.apply"
    assert event.result == "succeeded"
    assert result.audit_event_sha256 == event.event_sha256


def test_memory_apply_rejects_concurrent_change_before_backup(tmp_path: Path, app_paths) -> None:
    service, _source, target, plan, _diff, _plan_path = _prepared_memory(tmp_path, app_paths)
    target.write_text("# Memory\n\nChanged elsewhere.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after plan"):
        service.apply(plan, confirmation=plan.plan_id)
    assert "Changed elsewhere" in target.read_text(encoding="utf-8")


def test_memory_restore_is_plan_gated_and_creates_safety_backup(tmp_path: Path, app_paths) -> None:
    service, source, target, plan, _diff, _plan_path = _prepared_memory(tmp_path, app_paths)
    applied = service.apply(plan, confirmation=plan.plan_id)
    restore, restore_path = service.create_restore_plan(source.source_id, applied.backup_id)

    restored = service.apply_restore(restore, confirmation=restore.plan_id)

    assert restore_path.is_file()
    assert target.read_text(encoding="utf-8").endswith("Old preference.\n")
    assert restored.backup_id != applied.backup_id
    assert len(service.history(source.source_id)) == 2
