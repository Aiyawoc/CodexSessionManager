#!/usr/bin/env python3
"""Render deterministic README previews without contacting Codex."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codex_session_manager.config import AppPaths
from codex_session_manager.gui.application import ensure_application
from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.gui.i18n import GuiLanguage, save_language
from codex_session_manager.models import (
    CapabilityMatrix,
    ItemKind,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TrimAction,
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


def _snapshot(language: GuiLanguage) -> ThreadSnapshot:
    reference_time = datetime.now(UTC)
    if language is GuiLanguage.EN_US:
        title = "Context trimming workflow"
        cwd = "/Users/demo/Projects/CodexSessionManager"
        turn_specs = (
            (
                "turn-setup",
                """<codex_delegation>
<source>example.test/demo-thread</source>
</codex_delegation>

Map the conversation data flow and record the confirmed safety boundaries.""",
                """## Confirmed boundaries

- Write only through the App Server.
- Keep the source conversation unchanged.
- Revalidate the immutable plan before applying it.""",
            ),
            (
                "turn-debug",
                "Review the early diagnostic output. Contact: demo-user@example.test.",
                "The final verification supersedes the early probes; summarize the useful result.",
            ),
            (
                "turn-current",
                "Finish the context-trimming GUI and keep the current request protected.",
                "The current request, unresolved errors, and verification records remain intact.",
            ),
        )
        current_request = "Current user request"
        active_turn = "In-progress turn"
    else:
        title = "Codex 对话管理与上下文裁剪"
        cwd = "/Users/demo/项目/CodexSessionManager"
        turn_specs = (
            (
                "turn-setup",
                """<codex_delegation>
<source>example.test/demo-thread</source>
</codex_delegation>

请梳理当前对话的数据流，并记录已经确认的安全边界。""",
                """## 已确认的安全边界

- 只通过 App Server 写入。
- 原对话内容保持不变。
- 应用前重新校验不可变方案。""",
            ),
            (
                "turn-debug",
                "检查早期调试输出。示例联系邮箱：demo-user@example.test。",
                "最终验证已经替代早期探针，可将有用结论压缩为摘要。",
            ),
            (
                "turn-current",
                "完成上下文裁剪 GUI，并确保当前请求受到保护。",
                "当前请求、未解决错误和验证记录保持完整。",
            ),
        )
        current_request = "当前用户请求"
        active_turn = "进行中 turn"
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
                token_estimate=(1240, 860, 520)[index],
                hard_protected=protected,
                protected_reasons=(current_request,) if protected else (),
            ),
            ThreadItemSnapshot(
                id=f"{turn_id}-assistant",
                turn_id=turn_id,
                kind=ItemKind.ASSISTANT_MESSAGE,
                raw_type="agentMessage",
                role="assistant",
                text=assistant_text,
                token_estimate=(930, 640, 410)[index],
                hard_protected=protected,
                protected_reasons=(active_turn,) if protected else (),
            ),
        )
        turns.append(TurnSnapshot(id=turn_id, status="completed", items=items))
    return ThreadSnapshot(
        id="demo-thread-context-trim-0001",
        title=title,
        cwd=cwd,
        git_remote="https://example.test/CodexSessionManager.git",
        created_at=reference_time - timedelta(days=2),
        updated_at=reference_time - timedelta(days=1),
        status=ThreadStatus.IDLE,
        turns=tuple(turns),
        content_complete=True,
    )


def _task_snapshots(snapshot: ThreadSnapshot, language: GuiLanguage) -> tuple[ThreadSnapshot, ...]:
    """Return fictional task summaries that exercise project grouping."""

    if language is GuiLanguage.EN_US:
        same_project_titles = ("Encrypted backup verification", "Release acceptance review")
        other_title = "ChatGPT export import plan"
        other_cwd = "/Users/demo/Projects/ConversationLab"
    else:
        same_project_titles = ("加密备份复验", "测试版发布验收")
        other_title = "ChatGPT 导出导入计划"
        other_cwd = "/Users/demo/项目/ConversationLab"
    return (
        snapshot,
        snapshot.model_copy(
            update={
                "id": "demo-thread-backup-0002",
                "title": same_project_titles[0],
                "created_at": snapshot.created_at - timedelta(days=1),
                "updated_at": snapshot.updated_at - timedelta(days=1),
                "turns": (),
            }
        ),
        snapshot.model_copy(
            update={
                "id": "demo-thread-release-0003",
                "title": same_project_titles[1],
                "created_at": snapshot.created_at - timedelta(days=3),
                "updated_at": snapshot.updated_at - timedelta(days=2),
                "turns": (),
            }
        ),
        snapshot.model_copy(
            update={
                "id": "demo-thread-import-0004",
                "title": other_title,
                "cwd": other_cwd,
                "git_remote": "https://example.test/ConversationLab.git",
                "created_at": snapshot.created_at - timedelta(days=5),
                "updated_at": snapshot.updated_at - timedelta(days=4),
                "turns": (),
            }
        ),
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


def _select_turn(window: TrimReviewWindow, row: int) -> None:
    model = window.timeline_model
    if model is None:
        raise RuntimeError("preview timeline model is unavailable")
    index = model.index(row, 0)
    target = model.target_for(index)
    if target is None:
        raise RuntimeError(f"preview turn {row} is unavailable")
    window.ui.timelineView.setCurrentIndex(index)
    window._show_target(target)


def _select_item(window: TrimReviewWindow, turn_row: int, item_row: int) -> None:
    model = window.timeline_model
    if model is None:
        raise RuntimeError("preview timeline model is unavailable")
    parent = model.index(turn_row, 0)
    index = model.index(item_row, 0, parent)
    target = model.target_for(index)
    if target is None:
        raise RuntimeError(f"preview item {turn_row}:{item_row} is unavailable")
    window.ui.timelineView.setCurrentIndex(index)
    window._show_target(target)


def _set_action(window: TrimReviewWindow, action: TrimAction, summary: str | None = None) -> None:
    action_index = {
        TrimAction.KEEP: 0,
        TrimAction.EXCLUDE: 1,
        TrimAction.SUMMARY: 2,
        TrimAction.PROTECT: 3,
    }[action]
    window.ui.actionCombo.setCurrentIndex(action_index)
    if summary is not None:
        window.ui.summaryEdit.setPlainText(summary)


def _apply_scene(
    window: TrimReviewWindow,
    scene: str,
    language: GuiLanguage,
) -> None:
    summaries = {
        GuiLanguage.ZH_CN: "保留最终验证结论；移除已被替代的早期探针输出。",
        GuiLanguage.EN_US: "Keep the final verification result; remove superseded probe output.",
    }
    status = {
        GuiLanguage.ZH_CN: {
            "overview": "演示 1/6 · 选择需要审查的对话",
            "inspect": "演示 2/6 · 查看早期调试 turn",
            "summary": "演示 3/6 · 将可复用结论改为摘要",
            "exclude": "演示 4/6 · 排除已被替代的上下文",
            "markdown": "演示 5/6 · 预览 Markdown 与隐藏协议标签",
            "saved": "演示 6/6 · 保存不可变方案；原对话不变",
        },
        GuiLanguage.EN_US: {
            "overview": "Demo 1/6 · Select a conversation to review",
            "inspect": "Demo 2/6 · Inspect an early diagnostic turn",
            "summary": "Demo 3/6 · Summarize the reusable result",
            "exclude": "Demo 4/6 · Exclude superseded context",
            "markdown": "Demo 5/6 · Preview Markdown with protocol tags hidden",
            "saved": "Demo 6/6 · Save an immutable plan; source unchanged",
        },
    }[language]

    if scene == "overview":
        _select_turn(window, 0)
    elif scene == "inspect":
        _select_turn(window, 1)
    elif scene == "summary":
        _select_turn(window, 1)
        _set_action(window, TrimAction.SUMMARY, summaries[language])
    elif scene in {"exclude", "markdown", "saved"}:
        _select_turn(window, 1)
        _set_action(window, TrimAction.SUMMARY, summaries[language])
        _select_turn(window, 0)
        _set_action(window, TrimAction.EXCLUDE)
        if scene == "markdown":
            _select_item(window, 0, 1)
            window.ui.contentMarkdownButton.setChecked(True)
        elif scene == "saved":
            _select_turn(window, 1)
            # Keep README assets byte-stable: show the same successful status
            # as the real button without persisting a UUID-bearing fixture.
            window.ui.errorLabel.setText(window._t("plan_saved", plan_id="demo-plan-readme-0001"))
    else:
        raise ValueError(f"unsupported preview scene: {scene}")
    window.ui.taskListStatusLabel.setText(status[scene])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument(
        "--scene",
        choices=("overview", "inspect", "summary", "exclude", "markdown", "saved"),
        default="overview",
    )
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="csm-gui-preview-") as temporary:
        root = Path(temporary)
        os.environ["CSM_CACHE_DIR"] = str(root / "cache")
        app, _owned = ensure_application()
        paths = _paths(root)
        language = GuiLanguage.EN_US if args.language == "en" else GuiLanguage.ZH_CN
        save_language(paths.config_dir, language)
        snapshot = _snapshot(language)
        capabilities = _capabilities()
        plan = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
        window = TrimReviewWindow(paths=paths, load_task_list=False)
        window._document_loaded(0, ReviewDocument(snapshot, capabilities, plan))
        window.task_snapshots = _task_snapshots(snapshot, language)
        window._populate_task_list(window.task_snapshots)
        _apply_scene(window, args.scene, language)
        window.resize(1600, 900)
        window.show()
        app.processEvents()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(args.output), "PNG"):
            raise RuntimeError(f"failed to save GUI preview: {args.output}")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
