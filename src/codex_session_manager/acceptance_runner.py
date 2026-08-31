"""Automated, non-destructive first-delivery acceptance checks."""

from __future__ import annotations

import os
import platform
import tempfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime

from codex_session_manager.config import (
    AppPaths,
    bundled_age_keygen_path,
    bundled_age_path,
    private_atomic_create,
    stable_app_executable,
)
from codex_session_manager.hashing import (
    canonical_json_bytes,
    sealed_fingerprint,
    sha256_bytes,
    utc_now,
)
from codex_session_manager.models import FrozenModel
from codex_session_manager.version import __version__


class AutomatedCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AutomatedAcceptanceCheck(FrozenModel):
    name: str
    status: AutomatedCheckStatus
    required: bool
    detail: str
    evidence_sha256: str


class AutomatedAcceptanceReport(FrozenModel):
    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    tool_version: str
    platform: str
    architecture: str
    release_mode: bool
    checks: tuple[AutomatedAcceptanceCheck, ...]
    delivery_ready: bool
    production_ready: Literal[False] = False
    limitations: tuple[str, ...]
    report_sha256: str = ""

    def seal(self) -> Self:
        return self.model_copy(update={"report_sha256": sealed_fingerprint(self, "report_sha256")})

    def verify(self) -> None:
        if self.report_sha256 != sealed_fingerprint(self, "report_sha256"):
            raise ValueError("AutomatedAcceptanceReport SHA-256 mismatch")


CheckFunction = Callable[[AppPaths], str]


def _temp_paths(root: Path) -> AppPaths:
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


def _run_check(
    name: str,
    *,
    required: bool,
    paths: AppPaths,
    function: CheckFunction,
) -> AutomatedAcceptanceCheck:
    try:
        detail = function(paths)
    except FileNotFoundError as exc:
        status = AutomatedCheckStatus.FAILED if required else AutomatedCheckStatus.SKIPPED
        detail = str(exc)
    except BaseException as exc:
        status = AutomatedCheckStatus.FAILED
        detail = f"{type(exc).__name__}: {exc}"
    else:
        status = AutomatedCheckStatus.PASSED
    return AutomatedAcceptanceCheck(
        name=name,
        status=status,
        required=required,
        detail=detail,
        evidence_sha256=sha256_bytes(
            canonical_json_bytes(
                {
                    "name": name,
                    "status": status.value,
                    "required": required,
                    "detail": detail,
                }
            )
        ),
    )


def _mcp_boundary_check(paths: AppPaths) -> str:
    from codex_session_manager.mcp_server import McpApplication

    application = McpApplication(paths=paths, launcher=lambda _path: None)
    names = set(application.tools)
    allowed = {
        "inspect_conversation_inventory",
        "prepare_cleanup_suggestions",
        "open_cleanup_review",
        "prepare_context_suggestions",
        "open_context_review",
        "inspect_memory_source",
        "prepare_memory_suggestions",
        "open_memory_review",
        "get_pending_review_status",
        "open_review_demo",
    }
    if names != allowed:
        raise ValueError("MCP tool surface differs from the reviewed orchestration whitelist")
    forbidden = ("delete", "purge", "execute", "apply_memory", "apply_trim", "restore_apply")
    if any(token in name for name in names for token in forbidden):
        raise ValueError("MCP exposes a forbidden write executor")
    return f"{len(names)} reviewed orchestration tools; no write executor exposed"


def _memory_round_trip_check(paths: AppPaths) -> str:
    from codex_session_manager.audit import AuditStore
    from codex_session_manager.memory import (
        MemoryAction,
        MemorySelection,
        MemoryService,
        MemorySourceRegistry,
    )

    root = paths.data_dir.parent / "memory-fixture"
    root.mkdir(parents=True)
    source_path = root / "MEMORY.md"
    source_path.write_text("# Acceptance\n\nOriginal value.\n", encoding="utf-8")
    source = MemorySourceRegistry(paths).register(file_path=source_path, root_path=root)
    service = MemoryService(paths)
    snapshot = service.snapshot(source.source_id)
    segment = next(item for item in snapshot.segments if "Original value" in item.text)
    plan, _diff, _path = service.create_plan(
        source.source_id,
        (
            MemorySelection(
                segment_id=segment.segment_id,
                action=MemoryAction.REPLACE,
                replacement="Updated value.",
            ),
        ),
    )
    applied = service.apply(plan, confirmation=plan.plan_id)
    restore, _restore_path = service.create_restore_plan(source.source_id, applied.backup_id)
    service.apply_restore(restore, confirmation=restore.plan_id)
    if source_path.read_text(encoding="utf-8") != "# Acceptance\n\nOriginal value.\n":
        raise ValueError("memory restore did not reproduce the original bytes")
    if len(service.history(source.source_id)) != 2:
        raise ValueError("memory round trip did not retain both recoverable versions")
    with AuditStore(paths) as audit:
        audit.verify_chain()
        event_types = {event.event_type for event in audit.iter_events(limit=10)}
    if not {"memory.apply", "memory.restore"} <= event_types:
        raise ValueError("memory audit events are incomplete")
    return "registered source, plan, diff, backup, atomic apply, restore, and audit verified"


def _pending_lifecycle_check(paths: AppPaths) -> str:
    from codex_session_manager.hashing import utc_now
    from codex_session_manager.models import (
        CapabilityMatrix,
        ThreadSnapshot,
        ThreadStatus,
        TrimAction,
        TrimPlan,
        TrimSelection,
        TurnSnapshot,
    )
    from codex_session_manager.pending_plans import PendingTrimPlan, PendingTrimPlanStore
    from codex_session_manager.pending_service import PendingCheckResult, PendingPlanService

    turn = TurnSnapshot(id="acceptance-turn", status="completed")
    snapshot = ThreadSnapshot(
        id="acceptance-thread",
        status=ThreadStatus.IDLE,
        turns=(turn,),
        content_complete=True,
    )
    capabilities = CapabilityMatrix(
        codex_version="acceptance",
        codex_binary_sha256="a" * 64,
        initialize_fingerprint="acceptance",
        schema_sha256="b" * 64,
        stable_methods=("thread/read", "thread/start"),
        schema_complete=True,
    )
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(
                target_id=turn.id,
                target_level="turn",
                action=TrimAction.KEEP,
            ),
        ),
        estimated_tokens_after=0,
    )
    store = PendingTrimPlanStore(paths)
    pending = PendingTrimPlan(
        plan_id=plan.plan_id,
        plan_path=str(paths.plans_dir / "acceptance-trim.json"),
        plan_sha256=plan.plan_sha256,
        source_thread_id=plan.source_thread_id,
        source_fingerprint=plan.source_thread_fingerprint,
        created_at=utc_now(),
    )
    store.save(pending)
    service = PendingPlanService(store)
    result = service.check(
        pending,
        plan=plan,
        capabilities=capabilities,
        current_thread_fingerprint=plan.source_thread_fingerprint,
        thread_status=ThreadStatus.IDLE,
    )
    if result is not PendingCheckResult.READY:
        raise ValueError("pending plan did not become ready after complete safety checks")
    ready = store.load(store.path_for(plan.plan_id))
    cancelled = service.cancel(ready)
    if cancelled.status.value != "cancelled":
        raise ValueError("pending plan cancellation was not persisted")
    return "waiting, safety check, ready, and cancelled lifecycle persisted"


def _gui_memory_check(paths: AppPaths) -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from codex_session_manager.gui.application import ensure_application
    from codex_session_manager.gui.controller import TrimReviewWindow
    from codex_session_manager.gui.review_mode import ReviewMode
    from codex_session_manager.memory import MemorySourceRegistry

    root = paths.data_dir.parent / "gui-memory-fixture"
    root.mkdir(parents=True)
    source_path = root / "MEMORY.md"
    source_path.write_text("# GUI\n\nVisible segment.\n", encoding="utf-8")
    MemorySourceRegistry(paths).register(file_path=source_path, root_path=root)
    previous_cache = os.environ.get("CSM_CACHE_DIR")
    os.environ["CSM_CACHE_DIR"] = str(paths.cache_dir)
    try:
        _application, _created = ensure_application()
    finally:
        if previous_cache is None:
            os.environ.pop("CSM_CACHE_DIR", None)
        else:
            os.environ["CSM_CACHE_DIR"] = previous_cache
    window = TrimReviewWindow(
        paths=paths,
        load_task_list=False,
        mode=ReviewMode.MEMORY_EDIT,
    )
    try:
        if window.memory_snapshot is None or window.memory_timeline_model is None:
            raise ValueError("original GUI did not load the registered memory source")
        if window.memory_timeline_model.rowCount() < 1:
            raise ValueError("original GUI did not expose memory segments")
        if not window.ui.memoryRailButton.isChecked():
            raise ValueError("original GUI did not select the second memory rail button")
    finally:
        window.close()
    return "original GUI memory mode loaded the registered source and segment model"


def _age_check(_paths: AppPaths) -> str:
    age = bundled_age_path(allow_development_path=True)
    age_keygen = bundled_age_keygen_path(allow_development_path=True)
    if age is None or not age.is_file() or age_keygen is None or not age_keygen.is_file():
        raise FileNotFoundError("age or age-keygen executable is unavailable")
    return "age and age-keygen are available for managed encrypted conversation backups"


def _installed_app_check(_paths: AppPaths) -> str:
    executable = stable_app_executable()
    if not executable.is_file():
        raise FileNotFoundError("stable installed application executable is unavailable")
    return "stable installed application executable exists"


def _markdown(report: AutomatedAcceptanceReport) -> str:
    lines = [
        "# CodexSessionManager 首次交付自动验收",
        "",
        f"- 工具版本：`{report.tool_version}`",
        f"- 平台：`{report.platform} / {report.architecture}`",
        f"- 发布模式：`{str(report.release_mode).lower()}`",
        f"- 首次交付就绪：`{str(report.delivery_ready).lower()}`",
        "- 生产发布验收：`false`",
        "",
        "| 检查 | 必需 | 状态 | 说明 |",
        "|---|---:|---|---|",
    ]
    for check in report.checks:
        detail = check.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check.name}` | {str(check.required).lower()} | "
            f"`{check.status.value}` | {detail} |"
        )
    lines.extend(("", "## 限制", ""))
    lines.extend(f"- {value}" for value in report.limitations)
    lines.extend(("", f"报告 SHA-256：`{report.report_sha256}`", ""))
    return "\n".join(lines)


def run_automated_acceptance(
    output: Path,
    *,
    markdown_output: Path | None = None,
    release_mode: bool = False,
) -> dict[str, object]:
    """Run isolated checks without mutating the user's Codex data or memory files."""

    with tempfile.TemporaryDirectory(prefix="csm-acceptance-") as temporary:
        paths = _temp_paths(Path(temporary))
        paths.ensure()
        checks = (
            _run_check(
                "mcp_security_boundary",
                required=True,
                paths=paths,
                function=_mcp_boundary_check,
            ),
            _run_check(
                "memory_round_trip",
                required=True,
                paths=paths,
                function=_memory_round_trip_check,
            ),
            _run_check(
                "pending_plan_lifecycle",
                required=True,
                paths=paths,
                function=_pending_lifecycle_check,
            ),
            _run_check(
                "original_gui_memory_mode",
                required=True,
                paths=paths,
                function=_gui_memory_check,
            ),
            _run_check(
                "age_executable",
                required=release_mode,
                paths=paths,
                function=_age_check,
            ),
            _run_check(
                "stable_installed_app",
                required=release_mode,
                paths=paths,
                function=_installed_app_check,
            ),
        )
    delivery_ready = all(
        check.status is AutomatedCheckStatus.PASSED for check in checks if check.required
    )
    limitations = (
        "Codex desktop 本机 MCP 的 stdio 启动、工具发现和真实 GUI 行为需要在目标测试机人工验收",
        "HTTP MCP、远程连接器和 Tunnel 不属于本机 stdio 自动门禁；如启用需另行验收",
        "Apple 签名、公证和 Windows 原生运行不由本地自动检查声称完成",
        "永久删除仍是独立人工高风险流程",
        "production_ready 始终为 false；本报告只判断首次用户交付门槛",
    )
    report = AutomatedAcceptanceReport(
        generated_at=utc_now(),
        tool_version=__version__,
        platform=platform.system() or os.name,
        architecture=platform.machine() or "unknown",
        release_mode=release_mode,
        checks=checks,
        delivery_ready=delivery_ready,
        limitations=limitations,
    ).seal()
    report.verify()
    private_atomic_create(output, canonical_json_bytes(report))
    resolved_markdown = markdown_output or output.with_suffix(".md")
    private_atomic_create(resolved_markdown, _markdown(report).encode("utf-8"))
    return {
        "output": str(output),
        "markdown_output": str(resolved_markdown),
        "report_sha256": report.report_sha256,
        "delivery_ready": report.delivery_ready,
        "production_ready": report.production_ready,
        "failed_required_checks": tuple(
            check.name
            for check in report.checks
            if check.required and check.status is not AutomatedCheckStatus.PASSED
        ),
    }
