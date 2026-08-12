#!/usr/bin/env python3
"""Render a deterministic GUI preview without contacting Codex."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from codex_session_manager.config import AppPaths
from codex_session_manager.gui.application import ensure_application
from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.models import (
    CapabilityMatrix,
    ItemKind,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TurnSnapshot,
)
from codex_session_manager.trim import LocalTrimSuggester


def _paths(root: Path) -> AppPaths:
    data = root / "data"
    return AppPaths(
        data_dir=data,
        config_dir=root / "config",
        cache_dir=root / "cache",
        log_dir=root / "log",
        plans_dir=data / "plans",
        imports_dir=data / "imports",
        backups_dir=data / "backups",
        audit_db=data / "audit.sqlite3",
        codex_home=root / "codex-home",
    )


def _snapshot() -> ThreadSnapshot:
    turn_specs = (
        (
            "turn-setup",
            "请梳理当前任务的数据流，并记录已经确认的安全边界。",
            "已确认：只通过 App Server 写入；原任务保持不变。",
        ),
        (
            "turn-debug",
            "检查早期调试输出是否还需要保留。",
            "早期探针输出已被最终验证替代，可建议摘要。",
        ),
        (
            "turn-current",
            "实现上下文裁剪 GUI，并确保当前请求受到保护。",
            "正在实现 GUI；当前请求、未解决错误和验证记录保持完整。",
        ),
    )
    turns: list[TurnSnapshot] = []
    for index, (turn_id, user_text, assistant_text) in enumerate(turn_specs):
        protected = index == len(turn_specs) - 1
        items = (
            ThreadItemSnapshot(
                id=f"{turn_id}-user",
                turn_id=turn_id,
                kind=ItemKind.USER_MESSAGE,
                raw_type="userMessage",
                role="user",
                text=user_text,
                token_estimate=34,
                hard_protected=protected,
                protected_reasons=("当前用户请求",) if protected else (),
            ),
            ThreadItemSnapshot(
                id=f"{turn_id}-assistant",
                turn_id=turn_id,
                kind=ItemKind.ASSISTANT_MESSAGE,
                raw_type="agentMessage",
                role="assistant",
                text=assistant_text,
                token_estimate=42,
                hard_protected=protected,
                protected_reasons=("进行中 turn",) if protected else (),
            ),
        )
        turns.append(TurnSnapshot(id=turn_id, status="completed", items=items))
    return ThreadSnapshot(
        id="019f-demo-context-trim",
        title="Codex 对话管理实现",
        cwd="/Users/demo/项目/CodexSessionManager",
        git_remote="https://example.test/CodexSessionManager.git",
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        updated_at=datetime(2026, 8, 11, tzinfo=UTC),
        status=ThreadStatus.IDLE,
        turns=tuple(turns),
        content_complete=True,
    )


def _capabilities() -> CapabilityMatrix:
    return CapabilityMatrix(
        codex_version="preview",
        initialize_fingerprint="preview-init",
        schema_sha256="a" * 64,
        stable_methods=(
            "thread/read",
            "thread/start",
            "thread/fork",
            "thread/rollback",
            "thread/inject_items",
        ),
        schema_complete=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="csm-gui-preview-") as temporary:
        root = Path(temporary)
        os.environ["CSM_CACHE_DIR"] = str(root / "cache")
        app, _owned = ensure_application()
        paths = _paths(root)
        snapshot = _snapshot()
        capabilities = _capabilities()
        plan = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
        window = TrimReviewWindow(paths=paths, load_task_list=False)
        window._document_loaded(0, ReviewDocument(snapshot, capabilities, plan))
        window.task_snapshots = (snapshot,)
        window._populate_task_list((snapshot,))
        window.ui.taskListStatusLabel.setText("共 1 个任务 · 可按名称或 ID 搜索")
        window.show()
        app.processEvents()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(args.output), "PNG"):
            raise RuntimeError(f"failed to save GUI preview: {args.output}")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
