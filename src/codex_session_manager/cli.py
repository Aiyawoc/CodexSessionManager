"""Typer command-line interface for CodexSessionManager."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from codex_session_manager.acceptance import (
    AcceptanceScope,
    AcceptanceStage,
    AcceptanceStageName,
    AcceptanceStageResult,
    create_acceptance_report,
    save_acceptance_report,
)
from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.backup import (
    AgeBackend,
    BackupReader,
    DecryptionSpec,
    EncryptionSpec,
)
from codex_session_manager.cleanup import CleanupPolicy
from codex_session_manager.config import get_paths
from codex_session_manager.doctor import run_doctor
from codex_session_manager.hooks import HookInstaller
from codex_session_manager.importing import (
    ImportPlanner,
    LogicalImportExecutor,
    chatgpt_records,
    codex_records,
    record_from_backup_json,
    record_from_thread,
)
from codex_session_manager.inventory import InventoryFilter, InventoryService
from codex_session_manager.models import (
    ActionPlan,
    ImportPlan,
    PlanAction,
    ThreadStatus,
    TrimPlan,
)
from codex_session_manager.plans import load_plan_as
from codex_session_manager.schema_audit import (
    SchemaAuditReport,
    audit_local_schema,
    save_schema_audit_report,
)
from codex_session_manager.trim import LocalTrimSuggester, build_projection
from codex_session_manager.version import __version__
from codex_session_manager.workflows import ApplicationWorkflows

app = typer.Typer(
    name="csm",
    help="安全盘点、备份、导入、清理和裁剪 Codex 任务。",
    no_args_is_help=True,
)
threads_app = typer.Typer(help="盘点和查看 Codex 任务。")
cleanup_app = typer.Typer(help="生成或应用可恢复的归档/反归档计划。")
purge_app = typer.Typer(help="生成或人工应用永久删除计划。")
backup_app = typer.Typer(help="创建和验证 age 加密 .csmbackup。")
restore_app = typer.Typer(help="从 CSM 备份进行逻辑恢复。")
import_app = typer.Typer(help="导入其他来源的对话。")
chatgpt_app = typer.Typer(help="导入 ChatGPT 官方导出。")
codex_import_app = typer.Typer(help="导入其他账号或数据根中的 Codex rollout。")
trim_app = typer.Typer(help="审查、建议和应用派生式上下文裁剪。")
hook_app = typer.Typer(help="管理可选 PreCompact/PostCompact Hook。")
audit_app = typer.Typer(help="查看和验证 CSM 自有审计链。")
schema_app = typer.Typer(help="只读审计本地 Codex App Server schema。")
acceptance_app = typer.Typer(help="记录脱敏、分阶段的人工验收证据。")
gui_app = typer.Typer(help="打开统一桌面审查工作台或指定页面。")
mcp_app = typer.Typer(help="运行只读 MCP 编排服务。")
memory_app = typer.Typer(help="管理用户明确登记的本地 Markdown/文本记忆文件。")
memory_restore_app = typer.Typer(help="从 CSM 私有记忆版本中计划并执行恢复。")

app.add_typer(threads_app, name="threads")
app.add_typer(cleanup_app, name="cleanup")
app.add_typer(purge_app, name="purge")
app.add_typer(backup_app, name="backup")
app.add_typer(restore_app, name="restore")
app.add_typer(import_app, name="import")
import_app.add_typer(chatgpt_app, name="chatgpt")
import_app.add_typer(codex_import_app, name="codex")
app.add_typer(trim_app, name="trim")
app.add_typer(hook_app, name="hook")
app.add_typer(audit_app, name="audit")
app.add_typer(schema_app, name="schema")
app.add_typer(acceptance_app, name="acceptance")
app.add_typer(gui_app, name="gui")
app.add_typer(mcp_app, name="mcp")
app.add_typer(memory_app, name="memory")
memory_app.add_typer(memory_restore_app, name="restore")


@mcp_app.command("serve")
def mcp_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
) -> None:
    """启动只读 MCP HTTP 服务。"""

    from codex_session_manager.mcp_server import McpHttpConfig, serve_mcp_http

    serve_mcp_http(config=McpHttpConfig(host=host, port=port))


@acceptance_app.command("run")
def acceptance_run(
    output: Annotated[Path, typer.Option("--output")],
    markdown_output: Annotated[Path | None, typer.Option("--markdown-output")] = None,
) -> None:
    """运行非破坏性的自动验收检查。"""

    from codex_session_manager.acceptance_runner import run_automated_acceptance

    try:
        result = run_automated_acceptance(output, markdown_output=markdown_output)
    except (FileExistsError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法运行自动验收：{exc}") from exc
    _emit(result)


@acceptance_app.command("release")
def acceptance_release(
    output: Annotated[Path, typer.Option("--output")],
    markdown_output: Annotated[Path | None, typer.Option("--markdown-output")] = None,
) -> None:
    """增加 age 与稳定安装包门禁，生成首次交付发布验收报告。"""

    from codex_session_manager.acceptance_runner import run_automated_acceptance

    try:
        result = run_automated_acceptance(
            output,
            markdown_output=markdown_output,
            release_mode=True,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法运行发布验收：{exc}") from exc
    _emit(result)
    if not result["delivery_ready"]:
        raise typer.Exit(code=1)


@memory_app.command("register")
def memory_register(
    file_path: Path,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    allow_instruction_file: Annotated[
        bool,
        typer.Option("--allow-instruction-file"),
    ] = False,
) -> None:
    """显式登记一个允许由 CSM 管理的本地记忆文件。"""

    from codex_session_manager.memory import MemorySourceRegistry

    try:
        source = MemorySourceRegistry(get_paths()).register(
            file_path=file_path,
            root_path=root,
            allow_instruction_file=allow_instruction_file,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法登记记忆文件：{exc}") from exc
    _emit(source)


@memory_app.command("unregister")
def memory_unregister(source_id: str) -> None:
    """移除 CSM 登记，不删除或修改原文件。"""

    from codex_session_manager.memory import MemorySourceRegistry

    try:
        MemorySourceRegistry(get_paths()).unregister(source_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit({"source_id": source_id, "unregistered": True, "file_deleted": False})


def _memory_sources_payload() -> tuple[BaseModel, ...]:
    from codex_session_manager.memory import MemorySourceRegistry

    return MemorySourceRegistry(get_paths()).list()


@memory_app.command("sources")
def memory_sources() -> None:
    """列出明确登记的记忆来源。"""

    _emit(_memory_sources_payload())


@memory_app.command("list")
def memory_list() -> None:
    """列出明确登记的记忆来源。"""

    _emit(_memory_sources_payload())


@memory_app.command("show")
def memory_show(source_id: str) -> None:
    """读取一个登记来源并显示稳定分段与当前指纹。"""

    from codex_session_manager.memory import MemoryService

    try:
        _emit(MemoryService(get_paths()).snapshot(source_id))
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法读取记忆来源：{exc}") from exc


@memory_app.command("suggest")
def memory_suggest(source_id: str) -> None:
    """仅输出本地安全默认动作；不创建计划或写入文件。"""

    from codex_session_manager.memory import MemoryAction, MemoryService

    try:
        snapshot = MemoryService(get_paths()).snapshot(source_id)
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法读取记忆来源：{exc}") from exc
    _emit(
        {
            "source_id": source_id,
            "source_fingerprint": snapshot.source_fingerprint,
            "suggestions": tuple(
                {
                    "segment_id": segment.segment_id,
                    "action": (
                        MemoryAction.PROTECT.value if segment.protected else MemoryAction.KEEP.value
                    ),
                    "reason": segment.protection_reason or "MVP 默认保留，等待用户或 LLM 建议",
                }
                for segment in snapshot.segments
            ),
        }
    )


@memory_app.command("review")
def memory_review(source_id: str) -> None:
    """通过密封请求在原 GUI 的记忆模式中打开已登记来源。"""

    from codex_session_manager.gui.main import run_gui
    from codex_session_manager.memory import MemorySourceRegistry
    from codex_session_manager.review_requests import (
        ReviewOperation,
        ReviewRequest,
        ReviewRequestQueue,
        ReviewRequestStore,
        ReviewSource,
        codex_account_fingerprint,
    )

    paths = get_paths()
    try:
        source = MemorySourceRegistry(paths).get(source_id)
        request = ReviewRequest.create(
            operation=ReviewOperation.MEMORY_EDIT,
            source=ReviewSource.CLI,
            account_root_fingerprint=codex_account_fingerprint(paths),
            target_paths=(str(source.path),),
        )
        request_path = ReviewRequestStore(paths).save(request)
        ReviewRequestQueue(paths).enqueue(request_path)
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法准备记忆审查：{exc}") from exc
    raise typer.Exit(run_gui(request_path=request_path))


def _parse_memory_replacements(values: list[str] | None) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for value in values or ():
        segment_id, separator, replacement = value.partition("=")
        if not separator or not segment_id:
            raise typer.BadParameter("--replace 必须使用 SEGMENT_ID=TEXT")
        if segment_id in replacements:
            raise typer.BadParameter(f"重复 --replace segment id：{segment_id}")
        replacements[segment_id] = replacement
    return replacements


@memory_app.command("plan")
def memory_plan(
    source_id: str,
    delete: Annotated[list[str] | None, typer.Option("--delete")] = None,
    replace: Annotated[
        list[str] | None,
        typer.Option("--replace", help="可重复：SEGMENT_ID=TEXT"),
    ] = None,
    protect: Annotated[list[str] | None, typer.Option("--protect")] = None,
) -> None:
    """根据用户选择创建不可变 MemoryPlan 并显示 unified diff。"""

    from codex_session_manager.memory import (
        MemoryAction,
        MemorySelection,
        MemoryService,
    )

    replacements = _parse_memory_replacements(replace)
    action_ids = [*(delete or ()), *replacements, *(protect or ())]
    if len(action_ids) != len(set(action_ids)):
        raise typer.BadParameter("同一 segment 只能指定一个记忆动作")
    selections = tuple(
        [MemorySelection(segment_id=value, action=MemoryAction.DELETE) for value in delete or ()]
        + [
            MemorySelection(
                segment_id=segment_id,
                action=MemoryAction.REPLACE,
                replacement=text,
            )
            for segment_id, text in replacements.items()
        ]
        + [
            MemorySelection(segment_id=value, action=MemoryAction.PROTECT)
            for value in protect or ()
        ]
    )
    try:
        plan, diff, path = MemoryService(get_paths()).create_plan(source_id, selections)
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法创建记忆计划：{exc}") from exc
    _emit({"plan": plan, "path": path, "diff": diff})


@memory_app.command("apply")
def memory_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm", help="精确 plan_id")],
) -> None:
    """备份、并发复核、原子写入并重读验证一个 MemoryPlan。"""

    from codex_session_manager.memory import MemoryPlanStore, MemoryService

    try:
        plan = MemoryPlanStore(get_paths()).load(plan_path)
        _emit(MemoryService(get_paths()).apply(plan, confirmation=confirm))
    except (KeyError, OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(f"无法应用记忆计划：{exc}") from exc


@memory_app.command("history")
def memory_history(source_id: str) -> None:
    """列出经过完整哈希复核的私有记忆版本。"""

    from codex_session_manager.memory import MemoryService

    try:
        _emit(MemoryService(get_paths()).history(source_id))
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法读取记忆历史：{exc}") from exc


@memory_restore_app.command("plan")
def memory_restore_plan(source_id: str, backup_id: str) -> None:
    """为一个已验证私有版本创建不可变恢复计划。"""

    from codex_session_manager.memory import MemoryService

    try:
        plan, path = MemoryService(get_paths()).create_restore_plan(source_id, backup_id)
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法创建记忆恢复计划：{exc}") from exc
    _emit({"plan": plan, "path": path})


@memory_restore_app.command("apply")
def memory_restore_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm", help="精确 plan_id")],
) -> None:
    """先备份当前版本，再原子恢复已验证的旧版本。"""

    from codex_session_manager.memory import MemoryPlanStore, MemoryService

    try:
        plan = MemoryPlanStore(get_paths()).load_restore(plan_path)
        _emit(MemoryService(get_paths()).apply_restore(plan, confirmation=confirm))
    except (KeyError, OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(f"无法恢复记忆版本：{exc}") from exc


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _emit(value: Any) -> None:
    typer.echo(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True))


def _workflows() -> ApplicationWorkflows:
    return ApplicationWorkflows(paths=get_paths(), request_timeout=30)


def _identity_spec(identity: Path | None, passphrase: bool) -> DecryptionSpec:
    if passphrase and identity is not None:
        raise typer.BadParameter("--identity 与 --passphrase 不能同时使用")
    return DecryptionSpec(identity_file=identity, passphrase=passphrase)


def _aware_datetime(value: str | None, option: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(f"{option} 不是有效的 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise typer.BadParameter(f"{option} 必须包含时区，例如 2026-08-11T00:00:00+08:00")
    return parsed.astimezone(UTC)


def _inventory_filter(
    *,
    project: str | None = None,
    git_remote: str | None = None,
    source_kinds: list[str] | None = None,
    statuses: list[ThreadStatus] | None = None,
    archived: bool | None = None,
    pinned: bool | None = None,
    updated_before: str | None = None,
    updated_after: str | None = None,
    minimum_size: int | None = None,
    maximum_size: int | None = None,
    parent_id: str | None = None,
    search: str | None = None,
) -> InventoryFilter:
    return InventoryFilter(
        cwd=project,
        git_remote=git_remote,
        source_kinds=tuple(source_kinds or ()),
        archived=archived,
        pinned=pinned,
        statuses=tuple(statuses or ()),
        updated_before=_aware_datetime(updated_before, "--updated-before"),
        updated_after=_aware_datetime(updated_after, "--updated-after"),
        minimum_size=minimum_size,
        maximum_size=maximum_size,
        parent_id=parent_id,
        search=search,
    )


@app.command()
def version() -> None:
    """显示 CSM 版本。"""

    typer.echo(__version__)


@schema_app.command("audit")
def schema_audit(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="可选的不可覆盖 JSON 报告路径"),
    ] = None,
) -> None:
    """生成 schema、二进制和能力差异报告；不会连接或写入任务。"""

    report = audit_local_schema()
    if output is None:
        _emit(report)
        return
    try:
        save_schema_audit_report(report, output)
    except FileExistsError as exc:
        raise typer.BadParameter("--output 已存在；验收证据禁止覆盖") from exc
    _emit(
        {
            "output_name": output.name,
            "report_sha256": report.report_sha256,
            "conclusion": report.conclusion,
            "write_enabled": report.write_enabled,
        }
    )


def _parse_acceptance_stages(values: list[str] | None) -> tuple[AcceptanceStage, ...]:
    if not values:
        raise typer.BadParameter("至少提供一个 --stage NAME=passed|failed|not_run")
    stages: list[AcceptanceStage] = []
    for value in values:
        name, separator, result = value.partition("=")
        if not separator:
            raise typer.BadParameter(f"无效 --stage：{value}")
        try:
            stages.append(
                AcceptanceStage(
                    name=AcceptanceStageName(name),
                    result=AcceptanceStageResult(result),
                )
            )
        except ValueError as exc:
            raise typer.BadParameter(f"无效 --stage：{value}") from exc
    return tuple(stages)


@acceptance_app.command("report")
def acceptance_report(
    output: Path,
    schema_report_path: Annotated[Path, typer.Option("--schema-report")],
    scope: Annotated[AcceptanceScope, typer.Option("--scope")] = (
        AcceptanceScope.MACOS_REAL_ACCOUNT
    ),
    stage: Annotated[
        list[str] | None,
        typer.Option("--stage", help="可重复：固定阶段名=passed|failed|not_run"),
    ] = None,
    thread_id: Annotated[
        list[str] | None,
        typer.Option("--thread-id", help="可重复；报告中只保存域分隔哈希"),
    ] = None,
    plan_sha256: Annotated[list[str] | None, typer.Option("--plan-sha256")] = None,
    backup_manifest_sha256: Annotated[
        list[str] | None,
        typer.Option("--backup-manifest-sha256"),
    ] = None,
    audit_sha256: Annotated[str | None, typer.Option("--audit-sha256")] = None,
) -> None:
    """汇总人工阶段结果；不运行任何真实账号写操作。"""

    try:
        schema_report = SchemaAuditReport.model_validate_json(schema_report_path.read_bytes())
        report = create_acceptance_report(
            scope=scope,
            schema_report=schema_report,
            stages=_parse_acceptance_stages(stage),
            thread_ids=tuple(thread_id or ()),
            plan_sha256s=tuple(plan_sha256 or ()),
            backup_manifest_sha256s=tuple(backup_manifest_sha256 or ()),
            audit_sha256=audit_sha256,
        )
        save_acceptance_report(report, output)
    except FileExistsError as exc:
        raise typer.BadParameter("输出报告已存在；验收证据禁止覆盖") from exc
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"无法生成验收报告：{exc}") from exc
    _emit(
        {
            "output_name": output.name,
            "report_sha256": report.report_sha256,
            "production_ready": report.production_ready,
        }
    )


@app.command()
def doctor(
    skip_app_server: Annotated[bool, typer.Option("--skip-app-server")] = False,
) -> None:
    """验证 Python、Qt、age、App Server、插件和写权限。"""

    report = run_doctor(get_paths(), probe_app_server=not skip_app_server)
    _emit(report)
    if not report["ok"]:
        raise typer.Exit(1)


@threads_app.command("list")
def threads_list(
    project: Annotated[str | None, typer.Option("--project", help="精确 cwd")] = None,
    git_remote: Annotated[str | None, typer.Option("--git-remote")] = None,
    archived: Annotated[bool | None, typer.Option("--archived/--active-only")] = None,
    pinned: Annotated[bool | None, typer.Option("--pinned/--not-pinned")] = None,
    source_kind: Annotated[list[str] | None, typer.Option("--source-kind")] = None,
    status: Annotated[list[ThreadStatus] | None, typer.Option("--status")] = None,
    updated_before: Annotated[str | None, typer.Option("--updated-before")] = None,
    updated_after: Annotated[str | None, typer.Option("--updated-after")] = None,
    minimum_size: Annotated[int | None, typer.Option("--min-size", min=0)] = None,
    maximum_size: Annotated[int | None, typer.Option("--max-size", min=0)] = None,
    parent_id: Annotated[str | None, typer.Option("--parent-id")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
) -> None:
    """通过 App Server 列出任务摘要；不修复或改写 Codex 元数据。"""

    result = _workflows().list_threads(
        criteria=_inventory_filter(
            project=project,
            git_remote=git_remote,
            source_kinds=source_kind,
            statuses=status,
            archived=archived,
            pinned=pinned,
            updated_before=updated_before,
            updated_after=updated_after,
            minimum_size=minimum_size,
            maximum_size=maximum_size,
            parent_id=parent_id,
            search=search,
        )
    )
    _emit(
        {
            "capability_fingerprint": result.capabilities.fingerprint,
            "count": len(result.snapshots),
            "threads": [
                {
                    "id": item.id,
                    "title": item.title,
                    "cwd": item.cwd,
                    "git_remote": item.git_remote,
                    "updated_at": item.updated_at,
                    "status": item.status,
                    "archived": item.archived,
                    "pinned": item.pinned,
                    "size_bytes": item.size_bytes,
                    "descendants": item.spawned_descendant_ids,
                }
                for item in result.snapshots
            ],
        }
    )


@threads_app.command("show")
def threads_show(
    thread_id: str,
    include_content: Annotated[bool, typer.Option("--include-content")] = False,
) -> None:
    """读取单个任务；默认只输出摘要。"""

    result = _workflows().read_thread(thread_id, include_turns=include_content)
    _emit(
        {
            "capability_fingerprint": result.capabilities.fingerprint,
            "thread": result.snapshot,
        }
    )


@cleanup_app.command("plan")
def cleanup_plan(
    action: Annotated[str, typer.Option("--action", help="archive 或 unarchive")] = "archive",
    older_than_days: Annotated[int, typer.Option("--older-than-days", min=1)] = 90,
    project: Annotated[str | None, typer.Option("--project", help="只选择该根任务 cwd")] = None,
    git_remote: Annotated[str | None, typer.Option("--git-remote")] = None,
    source_kind: Annotated[list[str] | None, typer.Option("--source-kind")] = None,
    updated_before: Annotated[str | None, typer.Option("--updated-before")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
) -> None:
    """生成不可变归档/反归档计划，不执行写操作。"""

    try:
        plan_action = PlanAction(action)
    except ValueError as exc:
        raise typer.BadParameter("--action 必须是 archive 或 unarchive") from exc
    if plan_action not in {PlanAction.ARCHIVE, PlanAction.UNARCHIVE}:
        raise typer.BadParameter("--action 必须是 archive 或 unarchive")
    prepared = _workflows().prepare_cleanup_plan(
        action=plan_action,
        policy=CleanupPolicy(stale_after=timedelta(days=older_than_days)),
        criteria=_inventory_filter(
            project=project,
            git_remote=git_remote,
            source_kinds=source_kind,
            updated_before=updated_before,
            search=search,
        ),
    )
    _emit({"plan": prepared.plan, "path": prepared.path})


@cleanup_app.command("review")
def cleanup_review(
    request_path: Annotated[Path | None, typer.Option("--request")] = None,
    older_than_days: Annotated[int, typer.Option("--older-than-days", min=1)] = 90,
    project: Annotated[str | None, typer.Option("--project", help="只选择该根任务 cwd")] = None,
    git_remote: Annotated[str | None, typer.Option("--git-remote")] = None,
    source_kind: Annotated[list[str] | None, typer.Option("--source-kind")] = None,
    updated_before: Annotated[str | None, typer.Option("--updated-before")] = None,
    search: Annotated[str | None, typer.Option("--search")] = None,
) -> None:
    """生成只读清理建议并打开统一审查页，不创建 ActionPlan。"""

    from codex_session_manager.gui.main import run_gui

    if request_path is not None:
        if (
            any(
                value is not None
                for value in (project, git_remote, source_kind, updated_before, search)
            )
            or older_than_days != 90
        ):
            raise typer.BadParameter("--request 不能与候选筛选参数同时使用")
        raise typer.Exit(run_gui(request_path=request_path))

    from codex_session_manager.mcp_bridge import prepare_cleanup_review
    from codex_session_manager.review_requests import ReviewSource

    paths = get_paths()
    client, _capabilities = connect_and_probe()
    try:
        snapshots = InventoryService(client).list(include_turns=True)
    finally:
        client.close()
    criteria = _inventory_filter(
        project=project,
        git_remote=git_remote,
        source_kinds=source_kind,
        updated_before=updated_before,
        search=search,
    )
    prepared = prepare_cleanup_review(
        snapshots,
        paths=paths,
        older_than_days=older_than_days,
        criteria=criteria,
        source=ReviewSource.CLI,
    )
    if prepared is None:
        _emit(
            {
                "candidate_count": 0,
                "message": "当前筛选条件下没有满足本地安全规则的清理候选。",
            }
        )
        return
    _emit(
        {
            "candidate_count": len(prepared.target_ids),
            "request_id": prepared.request_id,
            "request_path": prepared.request_path,
            "suggestion_bundle_path": prepared.suggestion_bundle_path,
        }
    )
    raise typer.Exit(run_gui(request_path=Path(prepared.request_path)))


@cleanup_app.command("apply")
def cleanup_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm", help="精确 plan_id")],
) -> None:
    """复核漂移、备份和后代闭包后应用归档/反归档计划。"""

    plan = load_plan_as(plan_path, ActionPlan)
    if plan.action not in {PlanAction.ARCHIVE, PlanAction.UNARCHIVE}:
        raise typer.BadParameter("该计划不是 cleanup 计划")
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    result = _workflows().apply_action(plan, confirmation=confirm)
    _emit({"completed_roots": result.completed_ids, "plan_sha256": plan.plan_sha256})


@cleanup_app.command("reconcile")
def cleanup_reconcile(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm", help="精确 plan_id")],
) -> None:
    """复核并记录由 Codex App 原生任务工具完成的归档。"""

    plan = load_plan_as(plan_path, ActionPlan)
    if plan.action is not PlanAction.ARCHIVE:
        raise typer.BadParameter("只有 archive 计划可进行原生归档对账")
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    result = _workflows().reconcile_archive(plan)
    _emit({"reconciled_roots": result.completed_ids, "plan_sha256": plan.plan_sha256})


@purge_app.command("plan")
def purge_plan() -> None:
    """只为满足 14 天可信归档和已验证备份的任务生成删除计划。"""

    prepared = _workflows().prepare_purge_plan()
    _emit({"plan": prepared.plan, "path": prepared.path})


@purge_app.command("apply")
def purge_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm", help="精确 plan_id")],
    permanent_phrase: Annotated[str, typer.Option("--permanent-phrase")],
) -> None:
    """人工永久删除；有任何活动 Codex 进程、漂移或证据缺失即停止。"""

    plan = load_plan_as(plan_path, ActionPlan)
    if plan.action is not PlanAction.PURGE:
        raise typer.BadParameter("该计划不是 purge 计划")
    result = _workflows().apply_action(
        plan,
        confirmation=confirm,
        permanent_phrase=permanent_phrase,
    )
    _emit({"deleted_roots": result.completed_ids, "plan_sha256": plan.plan_sha256})


@backup_app.command("create")
def backup_create(
    destination: Path,
    thread: Annotated[list[str], typer.Option("--thread", help="可重复")],
    recipient: Annotated[str | None, typer.Option("--recipient")] = None,
    identity: Annotated[
        Path | None, typer.Option("--identity", help="创建后验证所用 identity 文件")
    ] = None,
    passphrase: Annotated[
        bool, typer.Option("--passphrase", help="由 age 在终端直接读取口令")
    ] = False,
    include_raw: Annotated[bool, typer.Option("--include-raw/--no-raw")] = True,
) -> None:
    """流式创建并完整复验 age 加密备份；不产生明文容器。"""

    if bool(recipient) == bool(passphrase):
        raise typer.BadParameter("必须且只能选择 --recipient 或 --passphrase")
    if recipient and identity is None:
        raise typer.BadParameter("recipient 模式必须提供 --identity 以完成创建后全包验证")
    encryption = (
        EncryptionSpec(mode="age-recipient", recipient=recipient)
        if recipient
        else EncryptionSpec(mode="age-passphrase")
    )
    try:
        result = _workflows().create_backup(
            destination,
            thread_ids=tuple(thread),
            encryption=encryption,
            verification_decryption=_identity_spec(identity, passphrase),
            include_raw=include_raw,
            expand_descendants=True,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        {
            "manifest": result.manifest,
            "covered_thread_ids": result.covered_thread_ids,
            "path": destination,
        }
    )


@backup_app.command("verify")
def backup_verify(
    source: Path,
    identity: Annotated[Path | None, typer.Option("--identity")] = None,
    passphrase: Annotated[bool, typer.Option("--passphrase")] = False,
) -> None:
    """完整解密并校验所有成员，不落地明文容器。"""

    verification = BackupReader(AgeBackend()).verify(
        source, decryption=_identity_spec(identity, passphrase)
    )
    manifest = verification.manifest
    with AuditStore(get_paths()) as audit:
        audit.record_verified_backup(verification, source)
        audit.append(
            event_type="backup.verify",
            actor="human",
            result="succeeded",
            target_ids=tuple(sorted(manifest.source_fingerprints)),
            details={"manifest_sha256": manifest.manifest_sha256},
        )
    _emit(manifest)


def _existing_records(service: InventoryService) -> tuple[Any, ...]:
    records = []
    for summary in service.list():
        try:
            records.append(record_from_thread(service.read(summary.id, include_turns=True)))
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"cannot complete import deduplication inventory for {summary.id}"
            ) from exc
    return tuple(records)


@restore_app.command("plan")
def restore_plan(
    source: Path,
    identity: Annotated[Path | None, typer.Option("--identity")] = None,
    passphrase: Annotated[bool, typer.Option("--passphrase")] = False,
    map_cwd: Annotated[str | None, typer.Option("--map-cwd")] = None,
) -> None:
    """验证备份并生成逻辑恢复计划；V1 不恢复 raw rollout。"""

    decryption = _identity_spec(identity, passphrase)
    reader = BackupReader(AgeBackend())
    verification = reader.verify(source, decryption=decryption)
    manifest = verification.manifest
    records = tuple(
        record_from_backup_json(value)
        for entry, value in reader.iter_logical_json(
            source, decryption=decryption, verified_manifest=manifest
        )
        if entry.kind == "logical"
    )
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        _client, capabilities, service = session.services()
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(service),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
        )
        path = session.plans.save(plan)
        _emit({"plan": plan, "path": path, "backup_manifest": manifest.manifest_sha256})


@restore_app.command("apply")
def restore_apply(
    plan_path: Path,
    source: Path,
    confirm: Annotated[str, typer.Option("--confirm")],
    identity: Annotated[Path | None, typer.Option("--identity")] = None,
    passphrase: Annotated[bool, typer.Option("--passphrase")] = False,
) -> None:
    """第二遍解密后创建新任务并注入逻辑历史，不重放工具。"""

    plan = load_plan_as(plan_path, ImportPlan)
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    decryption = _identity_spec(identity, passphrase)
    reader = BackupReader(AgeBackend())
    verification = reader.verify(source, decryption=decryption)
    manifest = verification.manifest
    records = tuple(
        record_from_backup_json(value)
        for entry, value in reader.iter_logical_json(
            source, decryption=decryption, verified_manifest=manifest
        )
        if entry.kind == "logical"
    )
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        client, capabilities, _inventory = session.services()
        created = LogicalImportExecutor(
            client=client,
            capabilities=capabilities,
            paths=paths,
            audit=session.audit,
        ).apply(plan, source=source, records=records)
        _emit({"created": created})


@chatgpt_app.command("plan")
def chatgpt_plan(
    source: Path,
    source_account: Annotated[str | None, typer.Option("--source-account")] = None,
    map_cwd: Annotated[str | None, typer.Option("--map-cwd")] = None,
    map_git_remote: Annotated[str | None, typer.Option("--map-git-remote")] = None,
) -> None:
    """流式解析 ChatGPT 官方导出并展开根到叶分支。"""

    records = tuple(chatgpt_records(source, source_account=source_account))
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        _client, capabilities, inventory = session.services()
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(inventory),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
            confirmed_git_remote=map_git_remote,
        )
        path = session.plans.save(plan)
        _emit({"plan": plan, "path": path})


@chatgpt_app.command("apply")
def chatgpt_apply(
    plan_path: Path,
    source: Path,
    confirm: Annotated[str, typer.Option("--confirm")],
    source_account: Annotated[str | None, typer.Option("--source-account")] = None,
) -> None:
    """复读原导出、校验 SHA 后创建新任务，不执行 sidecar 工具。"""

    plan = load_plan_as(plan_path, ImportPlan)
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    records = tuple(chatgpt_records(source, source_account=source_account))
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        client, capabilities, _inventory = session.services()
        created = LogicalImportExecutor(
            client=client,
            capabilities=capabilities,
            paths=paths,
            audit=session.audit,
        ).apply(plan, source=source, records=records)
        _emit({"created": created})


@codex_import_app.command("plan")
def codex_import_plan(
    source: Path,
    source_account: Annotated[str | None, typer.Option("--source-account")] = None,
    map_cwd: Annotated[str | None, typer.Option("--map-cwd")] = None,
    map_git_remote: Annotated[str | None, typer.Option("--map-git-remote")] = None,
) -> None:
    """流式读取 Codex JSONL 文件/目录，生成去重和隔离导入计划。"""

    records = tuple(codex_records(source, source_account=source_account))
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        _client, capabilities, inventory = session.services()
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(inventory),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
            confirmed_git_remote=map_git_remote,
        )
        path = session.plans.save(plan)
        _emit({"plan": plan, "path": path})


@codex_import_app.command("apply")
def codex_import_apply(
    plan_path: Path,
    source: Path,
    confirm: Annotated[str, typer.Option("--confirm")],
    source_account: Annotated[str | None, typer.Option("--source-account")] = None,
) -> None:
    """复读并校验 Codex rollout 后创建新任务；工具项保持惰性。"""

    plan = load_plan_as(plan_path, ImportPlan)
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    records = tuple(codex_records(source, source_account=source_account))
    paths = get_paths()
    workflows = ApplicationWorkflows(paths=paths, request_timeout=30)
    with workflows.session() as session:
        client, capabilities, _inventory = session.services()
        created = LogicalImportExecutor(
            client=client,
            capabilities=capabilities,
            paths=paths,
            audit=session.audit,
        ).apply(plan, source=source, records=records)
        _emit({"created": created})


@trim_app.command("review")
def trim_review(thread_id: str | None = None) -> None:
    """打开独立 PySide6 裁剪 GUI。"""

    from codex_session_manager.gui.main import run_gui

    raise typer.Exit(run_gui(thread_id=thread_id))


@gui_app.command("open")
def gui_open(
    request_path: Annotated[Path | None, typer.Option("--request")] = None,
    page: Annotated[
        str | None,
        typer.Option(
            "--page",
            help="cleanup、context、memory、pending 或 backup_restore",
        ),
    ] = None,
    thread_id: Annotated[str | None, typer.Option("--thread")] = None,
) -> None:
    """打开统一主窗口、密封审查请求或兼容的上下文审查窗口。"""

    targets = sum(value is not None for value in (request_path, page, thread_id))
    if targets > 1:
        raise typer.BadParameter("--request、--page 与 --thread 只能指定一个")

    from codex_session_manager.gui.main import run_gui
    from codex_session_manager.gui.single_instance import DesktopPage

    parsed_page: DesktopPage | None = None
    if page is not None:
        try:
            parsed_page = DesktopPage(page)
        except ValueError as exc:
            allowed = "、".join(item.value for item in DesktopPage)
            raise typer.BadParameter(f"--page 必须是：{allowed}") from exc
    raise typer.Exit(
        run_gui(
            thread_id=thread_id,
            request_path=request_path,
            page=parsed_page,
        )
    )


@trim_app.command("suggest")
def trim_suggest(thread_id: str) -> None:
    """仅用本地规则生成并保存 TrimPlan；内容 AI 默认关闭。"""

    workflows = _workflows()
    result = workflows.read_thread(thread_id, include_turns=True)
    plan = LocalTrimSuggester().suggest(
        result.snapshot,
        capabilities=result.capabilities,
    )
    path = workflows.save_plan(plan)
    projection = build_projection(result.snapshot, plan)
    _emit({"plan": plan, "path": path, "projection": projection})


@trim_app.command("apply")
def trim_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm")],
) -> None:
    """任务 idle/notLoaded 且 fingerprint 一致时创建派生精简任务。"""

    plan = load_plan_as(plan_path, TrimPlan)
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    target_id = _workflows().apply_trim(plan)
    _emit({"source_thread_id": plan.source_thread_id, "derived_thread_id": target_id})


@hook_app.command("status")
def hook_status() -> None:
    """显示稳定 .app Hook 是否已配置；不修改配置。"""

    _emit(HookInstaller(get_paths()).status())


@hook_app.command("install")
def hook_install(
    yes: Annotated[bool, typer.Option("--yes", help="确认修改用户级 hooks.json")] = False,
) -> None:
    """合并用户级 Hook；安装后仍需在 Codex /hooks 中审查并信任。"""

    if not yes:
        raise typer.BadParameter("请阅读计划后使用 --yes 明确确认")
    path = HookInstaller(get_paths()).install()
    _emit({"installed": str(path), "trust_required": True})


@hook_app.command("uninstall")
def hook_uninstall(
    yes: Annotated[bool, typer.Option("--yes", help="确认移除 CSM Hook")] = False,
) -> None:
    """仅移除 CSM 自己的 Hook 条目，并保留原配置备份。"""

    if not yes:
        raise typer.BadParameter("使用 --yes 明确确认")
    path = HookInstaller(get_paths()).uninstall()
    _emit({"updated": str(path)})


@audit_app.command("show")
def audit_show(
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """显示不含对话正文或密钥的 CSM 审计事件。"""

    with AuditStore(get_paths()) as audit:
        _emit(tuple(audit.iter_events(limit=limit)))


@audit_app.command("verify")
def audit_verify() -> None:
    """验证审计事件哈希链。"""

    with AuditStore(get_paths()) as audit:
        audit.verify_chain()
    _emit({"ok": True})


if __name__ == "__main__":
    app()
