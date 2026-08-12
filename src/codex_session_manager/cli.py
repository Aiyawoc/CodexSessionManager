"""Typer command-line interface for CodexSessionManager."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.backup import (
    AgeBackend,
    BackupReader,
    BackupService,
    DecryptionSpec,
    EncryptionSpec,
)
from codex_session_manager.cleanup import CleanupExecutor, CleanupPlanner, CleanupPolicy
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
from codex_session_manager.inventory import (
    InventoryFilter,
    InventoryService,
    merge_thread_detail,
)
from codex_session_manager.models import (
    ActionPlan,
    ImportPlan,
    PlanAction,
    ThreadStatus,
    TrimPlan,
)
from codex_session_manager.plans import PlanStore, load_plan_as
from codex_session_manager.trim import LocalTrimSuggester, TrimExecutor, build_projection
from codex_session_manager.version import __version__

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

    client, capabilities = connect_and_probe()
    try:
        snapshots = InventoryService(client).list(
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
                "capability_fingerprint": capabilities.fingerprint,
                "count": len(snapshots),
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
                    for item in snapshots
                ],
            }
        )
    finally:
        client.close()


@threads_app.command("show")
def threads_show(
    thread_id: str,
    include_content: Annotated[bool, typer.Option("--include-content")] = False,
) -> None:
    """读取单个任务；默认只输出摘要。"""

    client, capabilities = connect_and_probe()
    try:
        snapshot = InventoryService(client).read(thread_id, include_turns=include_content)
        _emit({"capability_fingerprint": capabilities.fingerprint, "thread": snapshot})
    finally:
        client.close()


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

    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        snapshots = InventoryService(client).list(include_turns=True)
        planner = CleanupPlanner(CleanupPolicy(stale_after=timedelta(days=older_than_days)))
        criteria = _inventory_filter(
            project=project,
            git_remote=git_remote,
            source_kinds=source_kind,
            updated_before=updated_before,
            search=search,
        )
        if action == "archive":
            plan = planner.plan_archive(snapshots, capabilities, criteria=criteria)
        elif action == "unarchive":
            plan = planner.plan_unarchive(snapshots, capabilities, criteria=criteria)
        else:
            raise typer.BadParameter("--action 必须是 archive 或 unarchive")
        path = PlanStore(paths).save(plan)
        _emit({"plan": plan, "path": path})
    finally:
        client.close()


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
    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            completed = CleanupExecutor(
                client=client,
                inventory=InventoryService(client),
                capabilities=capabilities,
                audit=audit,
            ).apply(plan, confirmation=confirm)
        _emit({"completed_roots": completed, "plan_sha256": plan.plan_sha256})
    finally:
        client.close()


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
    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            completed = CleanupExecutor(
                client=client,
                inventory=InventoryService(client),
                capabilities=capabilities,
                audit=audit,
            ).reconcile_native_archive(plan)
        _emit({"reconciled_roots": completed, "plan_sha256": plan.plan_sha256})
    finally:
        client.close()


@purge_app.command("plan")
def purge_plan() -> None:
    """只为满足 14 天可信归档和已验证备份的任务生成删除计划。"""

    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        snapshots = InventoryService(client).list(include_turns=True)
        with AuditStore(paths) as audit:
            plan = CleanupPlanner().plan_purge(snapshots, capabilities, audit)
        path = PlanStore(paths).save(plan)
        _emit({"plan": plan, "path": path})
    finally:
        client.close()


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
    paths = get_paths()
    client, capabilities = connect_and_probe(experimental_api=True)
    try:
        with AuditStore(paths) as audit:
            completed = CleanupExecutor(
                client=client,
                inventory=InventoryService(client),
                capabilities=capabilities,
                audit=audit,
            ).apply(
                plan,
                confirmation=confirm,
                permanent_phrase=permanent_phrase,
            )
        _emit({"deleted_roots": completed, "plan_sha256": plan.plan_sha256})
    finally:
        client.close()


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
    paths = get_paths()
    paths.ensure()
    backend = AgeBackend()
    client, _capabilities = connect_and_probe()
    try:
        service = InventoryService(client)
        all_summaries = {item.id: item for item in service.list()}
        missing = [thread_id for thread_id in thread if thread_id not in all_summaries]
        if missing:
            raise typer.BadParameter(f"找不到任务：{', '.join(missing)}")
        snapshots = tuple(
            merge_thread_detail(
                all_summaries[thread_id],
                service.read(thread_id, include_turns=True),
            )
            for thread_id in thread
        )
        encryption = (
            EncryptionSpec(mode="age-recipient", recipient=recipient)
            if recipient
            else EncryptionSpec(mode="age-passphrase")
        )
        with AuditStore(paths) as audit:
            manifest = BackupService(
                client=client,
                paths=paths,
                backend=backend,
                audit=audit,
            ).create(
                destination,
                snapshots=snapshots,
                encryption=encryption,
                verification_decryption=_identity_spec(identity, passphrase),
                include_raw=include_raw,
            )
        _emit({"manifest": manifest, "path": destination})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        service = InventoryService(client)
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(service),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
        )
        path = PlanStore(paths).save(plan)
        _emit({"plan": plan, "path": path, "backup_manifest": manifest.manifest_sha256})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            created = LogicalImportExecutor(
                client=client,
                capabilities=capabilities,
                paths=paths,
                audit=audit,
            ).apply(plan, source=source, records=records)
        _emit({"created": created})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(InventoryService(client)),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
            confirmed_git_remote=map_git_remote,
        )
        path = PlanStore(paths).save(plan)
        _emit({"plan": plan, "path": path})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            created = LogicalImportExecutor(
                client=client,
                capabilities=capabilities,
                paths=paths,
                audit=audit,
            ).apply(plan, source=source, records=records)
        _emit({"created": created})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        plan = ImportPlanner(paths).plan(
            source=source,
            records=records,
            existing=_existing_records(InventoryService(client)),
            capabilities=capabilities,
            confirmed_cwd=map_cwd,
            confirmed_git_remote=map_git_remote,
        )
        path = PlanStore(paths).save(plan)
        _emit({"plan": plan, "path": path})
    finally:
        client.close()


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
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            created = LogicalImportExecutor(
                client=client,
                capabilities=capabilities,
                paths=paths,
                audit=audit,
            ).apply(plan, source=source, records=records)
        _emit({"created": created})
    finally:
        client.close()


@trim_app.command("review")
def trim_review(thread_id: str | None = None) -> None:
    """打开独立 PySide6 裁剪 GUI。"""

    from codex_session_manager.gui.main import run_gui

    raise typer.Exit(run_gui(thread_id=thread_id))


@trim_app.command("suggest")
def trim_suggest(thread_id: str) -> None:
    """仅用本地规则生成并保存 TrimPlan；内容 AI 默认关闭。"""

    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        snapshot = InventoryService(client).read(thread_id, include_turns=True)
        plan = LocalTrimSuggester().suggest(snapshot, capabilities=capabilities)
        path = PlanStore(paths).save(plan)
        projection = build_projection(snapshot, plan)
        _emit({"plan": plan, "path": path, "projection": projection})
    finally:
        client.close()


@trim_app.command("apply")
def trim_apply(
    plan_path: Path,
    confirm: Annotated[str, typer.Option("--confirm")],
) -> None:
    """任务 idle 且 fingerprint 一致时创建派生精简任务。"""

    plan = load_plan_as(plan_path, TrimPlan)
    if confirm != plan.plan_id:
        raise typer.BadParameter("--confirm 必须等于精确 plan_id")
    paths = get_paths()
    client, capabilities = connect_and_probe()
    try:
        with AuditStore(paths) as audit:
            target_id = TrimExecutor(
                client=client,
                inventory=InventoryService(client),
                capabilities=capabilities,
                audit=audit,
            ).apply(plan)
        _emit({"source_thread_id": plan.source_thread_id, "derived_thread_id": target_id})
    finally:
        client.close()


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
