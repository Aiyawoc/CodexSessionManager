from __future__ import annotations

import re
import shlex
from pathlib import Path

from typer.testing import CliRunner

from codex_session_manager.cli import app

PROJECT_ROOT = Path(__file__).parents[1]
SKILL_ROOT = PROJECT_ROOT / "skills" / "manage-codex-sessions"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
COMMANDS_PATH = SKILL_ROOT / "references" / "commands.md"
OPENAI_YAML_PATH = SKILL_ROOT / "agents" / "openai.yaml"

README_COMMAND_CONTRACTS = {
    "README-cn.md": (
        PROJECT_ROOT / "README-cn.md",
        (
            "| `csm restore plan` | 生成逻辑恢复计划；当前不写入 Codex |",
            "| `csm import {chatgpt\\|codex} plan ...` | 生成导入计划；当前不写入 Codex |",
            "| `csm trim review\\|suggest` | GUI/人工审查与本地投影建议 |",
        ),
    ),
    "README.md": (
        PROJECT_ROOT / "README.md",
        (
            "| `csm restore plan` | Create a logical restore plan; it does not write to Codex |",
            "| `csm import {chatgpt\\|codex} plan ...` | Create an import plan; it does not write to Codex |",
            "| `csm trim review\\|suggest` | GUI/manual review and local projection suggestions |",
        ),
    ),
}

README_FORBIDDEN_COMMAND_ROWS = (
    "`csm restore plan\\|apply`",
    "`csm import {chatgpt\\|codex} ...`",
    "`csm trim review\\|suggest\\|apply`",
    "`csm trim apply`",
)

CURRENT_CONTRACT_DOCUMENTS = {
    "AGENTS.md": (
        PROJECT_ROOT / "AGENTS.md",
        (
            "当前边界是版本无关、契约敏感",
            "第一版任务管理只提供盘点、备份、批量归档和反归档",
            "当前上下文能力仅限审查与投影计划",
            "MCP 不暴露归档/反归档执行器",
        ),
    ),
    "README-cn.md": (
        PROJECT_ROOT / "README-cn.md",
        (
            "当前边界是版本无关、契约敏感",
            "第一版任务管理只提供盘点、备份、批量归档和反归档；永久删除、重命名、恢复/导入写入、上下文应用和 MCP 写入均不可用。",
            "当前完全不提供永久删除的资格盘点、计划、GUI、CLI、Skill、MCP 或执行器",
            "当前 Codex 版本、二进制散列和全量 schema 散列是诊断与计划失效证据，不是归档授权条件。",
        ),
    ),
    "README.md": (
        PROJECT_ROOT / "README.md",
        (
            "The boundary is version-independent and contract-sensitive",
            "The first-version task-management write surface is batch archive and unarchive only; permanent deletion, rename, restore/import writes, context application, and MCP writes are unavailable.",
            "The current Codex version, binary hash, and full schema hash are diagnostic and plan-invalidation evidence, not archive authorization conditions.",
            "archive and unarchive are evaluated against static, human-reviewed minimal operation contracts.",
        ),
    ),
    "acceptance/README.md": (
        PROJECT_ROOT / "docs" / "acceptance" / "README.md",
        (
            "第一版 Codex 写能力：仅批量归档和反归档",
            "当前边界是版本无关、契约敏感",
            "永久删除历史：已从当前能力与二期交付中退役",
            "当前阶段：继续完成 v1.1 其它功能验收",
        ),
    ),
    "local-controlled-v1.1.0.md": (
        PROJECT_ROOT / "docs" / "acceptance" / "local-controlled-v1.1.0.md",
        (
            "当前边界是版本无关、契约敏感",
            "当前 Codex 在线任务仅允许 `archive`/`unarchive` 执行",
            "不得执行永久删除、重命名或其它当前不可用写入",
            "MCP 工具恰好十个，没有 archive/unarchive executor",
        ),
    ),
    "context-projection-plan.md": (
        PROJECT_ROOT
        / "docs"
        / "CodexSessionManager-v1.1-context-projection-and-sensitive-data-plan.md",
        (
            "当前 Codex 在线任务仅允许 `archive`/`unarchive` 执行",
            "上下文审查与投影计划可用，但应用不可用",
            "第一版任务管理只提供盘点、备份、批量归档和反归档，不提供永久删除能力。",
            "标题修改/重命名不属于第一版范围且当前不可用；只有在 v1.1 之后另行完成产品决策、受支持的操作契约和真实验收",
        ),
    ),
    "phase-two-plan.md": (
        PROJECT_ROOT / "docs" / "CodexSessionManager 二期最终实施计划.md",
        (
            "二期 D1+ 未启动；未经明确要求不得开始。",
            "当前 Codex 在线任务仅允许 `archive`/`unarchive` 执行",
            "标题修改/重命名不属于第一版范围且当前不可用；若在 v1.1 之后仍需研究，必须另行作出产品决策、定义受支持的操作契约并完成真实验收",
            "本轮不启动 D1+",
        ),
    ),
    "SKILL.md": (
        SKILL_PATH,
        (
            "当前边界是版本无关、契约敏感",
            "当前 Codex 版本、二进制散列和全量 schema 散列是诊断与计划失效证据，不是归档授权条件",
            "永久删除当前不提供资格盘点、计划、GUI、CLI、Skill、MCP 或执行器",
            "MCP 不提供 archive/unarchive executors",
        ),
    ),
    "safety.md": (
        SKILL_ROOT / "references" / "safety.md",
        (
            "当前边界是版本无关、契约敏感",
            "上下文审查与投影计划只保存 CSM 计划，不修改 Codex",
            "当前 Codex 任务写入仅为 `thread/archive` 和 `thread/unarchive`",
            "MCP 只读、建议和打开审查 GUI，不提供 archive/unarchive executor",
        ),
    ),
    "commands.md": (
        COMMANDS_PATH,
        (
            "csm cleanup plan/apply",
            "永久删除、重命名、restore/import 写入和上下文应用不属于当前能力",
            "第一版不提供 restore/import 的 Codex 写入 apply 步骤",
            "第一版不提供 `trim apply` 的 Codex 写入步骤",
        ),
    ),
}

HISTORICAL_DOCUMENTS = {
    "phase-2.5-purge-closure.md": (
        PROJECT_ROOT / "docs" / "acceptance" / "v1.1.0-phase-2.5-permanent-purge-closure.md",
        "> **SUPERSEDED（2026-09-02）**",
        (
            "../adr/0011-version-independent-operation-contracts.md",
            "README.md",
            "永久删除（purge）已从第一版退休",
            "精确版本/画像授权归档写入仅属历史",
        ),
    ),
    "adr-0010-manual-purge.md": (
        PROJECT_ROOT / "docs" / "adr" / "0010-manual-purge-without-fixed-delay.md",
        "> **SUPERSEDED（2026-09-02）**",
        (
            "0011-version-independent-operation-contracts.md",
            "../acceptance/README.md",
            "永久删除（purge）已从第一版退休",
            "精确版本/画像授权归档写入仅属历史",
        ),
    ),
    "adr-0002-closures.md": (
        PROJECT_ROOT / "docs" / "adr" / "0002-plans-closures-and-derived-trimming.md",
        "> **SUPERSEDED IN PART（2026-09-02）**",
        (
            "0011-version-independent-operation-contracts.md",
            "../acceptance/README.md",
            "仅永久删除（purge）及旧精确版本/画像授权归档写入的表述被取代",
            "不可变计划、完整后代闭包、上下文应用延期和来源任务保护决策继续有效",
        ),
    ),
    "adr-0009-context-projection.md": (
        PROJECT_ROOT / "docs" / "adr" / "0009-defer-context-projection-application.md",
        "> **SUPERSEDED IN PART（2026-09-02）**",
        (
            "0011-version-independent-operation-contracts.md",
            "../acceptance/README.md",
            "仅永久删除（purge）及旧精确版本/画像授权归档写入的表述被取代",
            "不可变计划、完整后代闭包、上下文应用延期和来源任务保护决策继续有效",
        ),
    ),
}

CURRENT_DOC_PATHS = (
    *(path for path, _ in CURRENT_CONTRACT_DOCUMENTS.values()),
    PROJECT_ROOT / "CONTEXT.md",
    PROJECT_ROOT / "docs" / "acceptance" / "app-server-schema-approval.md",
    PROJECT_ROOT / "docs" / "acceptance" / "first-delivery-v1.1.0.md",
    PROJECT_ROOT / "docs" / "acceptance" / "formal-release-manual-v1.1.0.md",
    PROJECT_ROOT / "docs" / "releases" / "v1.1.0-first-delivery.md",
)

EXPECTED_COMMAND_PATHS = {
    ("doctor",),
    ("threads", "list"),
    ("threads", "show"),
    ("cleanup", "review"),
    ("cleanup", "plan"),
    ("cleanup", "apply"),
    ("cleanup", "reconcile"),
    ("backup", "create"),
    ("backup", "verify"),
    ("restore", "plan"),
    ("import", "chatgpt", "plan"),
    ("import", "codex", "plan"),
    ("trim", "review"),
    ("trim", "suggest"),
    ("hook", "status"),
    ("hook", "install"),
    ("hook", "uninstall"),
    ("mcp", "serve"),
    ("audit", "verify"),
    ("audit", "show"),
    ("schema", "audit"),
    ("acceptance", "report"),
    ("acceptance", "run"),
    ("acceptance", "release"),
    ("gui", "open"),
    ("memory", "register"),
    ("memory", "unregister"),
    ("memory", "sources"),
    ("memory", "list"),
    ("memory", "show"),
    ("memory", "suggest"),
    ("memory", "review"),
    ("memory", "plan"),
    ("memory", "apply"),
    ("memory", "history"),
    ("memory", "restore", "plan"),
    ("memory", "restore", "apply"),
}


def _documented_command_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for line in COMMANDS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("csm "):
            continue
        tokens = shlex.split(stripped)[1:]
        if tokens[0] == "import" or (
            tokens[0] == "memory" and len(tokens) >= 2 and tokens[1] == "restore"
        ):
            paths.add(tuple(tokens[:3]))
        elif tokens[0] in {
            "threads",
            "cleanup",
            "backup",
            "restore",
            "trim",
            "hook",
            "mcp",
            "audit",
            "schema",
            "acceptance",
            "gui",
            "memory",
        }:
            paths.add(tuple(tokens[:2]))
        else:
            paths.add((tokens[0],))
    return paths


def test_skill_package_metadata_references_and_invocation_policy() -> None:
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(?P<body>.*?)\n---\n", skill_text, re.DOTALL)
    assert frontmatter is not None
    assert re.search(r"^name:\s*manage-codex-sessions\s*$", frontmatter["body"], re.MULTILINE)
    assert re.search(r"^description:\s*\S", frontmatter["body"], re.MULTILINE)

    linked_paths = {
        match
        for match in re.findall(r"\[[^]]+\]\(([^)]+)\)", skill_text)
        if "://" not in match and not match.startswith("#")
    }
    assert linked_paths == {"references/commands.md", "references/safety.md"}
    for linked_path in linked_paths:
        target = SKILL_ROOT / linked_path
        assert target.is_file()
        assert not target.is_symlink()

    metadata = OPENAI_YAML_PATH.read_text(encoding="utf-8")
    assert re.search(r"^\s*allow_implicit_invocation:\s*false\s*$", metadata, re.MULTILINE)


def test_skill_keeps_stable_entry_and_fail_closed_safety_contract() -> None:
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    assert "command -v csm" in skill_text
    assert "Get-Command csm" in skill_text
    assert "~/Applications/CodexSessionManager.app/Contents/MacOS/CodexSessionManager" in skill_text
    assert "%LOCALAPPDATA%\\CodexSessionManager\\CodexSessionManager.exe" in skill_text
    assert "不要回退到 `uv`、`.venv` 或系统 Python" in skill_text
    assert "禁止直接修改 Codex JSONL、SQLite、认证或配置" in skill_text
    assert "只执行读取、备份、验证和计划" in skill_text
    assert "只有用户明确要求启用时才运行 `csm hook install --yes`" in skill_text


def test_current_docs_use_version_independent_contract_sensitive_boundary() -> None:
    for name, (path, markers) in CURRENT_CONTRACT_DOCUMENTS.items():
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        assert not missing, (name, missing)


def test_owned_docs_keep_current_operation_contract_wording() -> None:
    expectations = {
        "SKILL.md": (
            SKILL_PATH,
            (
                "Codex 逻辑恢复当前仅生成 `plan`，没有 Codex 写入 `apply`",
                "记忆功能只管理明确登记的本地文件",
            ),
        ),
        "first-delivery-release.md": (
            PROJECT_ROOT / "docs" / "releases" / "v1.1.0-first-delivery.md",
            (
                "首次交付当前门禁是 Codex Desktop 本机 MCP stdio（`csm mcp stdio`）",
                "Streamable HTTP（`csm mcp serve`）仅用于可选本机诊断",
                "真实 ChatGPT 与固定 Cloudflare Tunnel 属于可选/历史远程 profile",
                "历史基线：2026-08-18 本地候选证据",
                "不代表当前 HEAD 的证据",
            ),
        ),
        "formal-release-manual.md": (
            PROJECT_ROOT / "docs" / "acceptance" / "formal-release-manual-v1.1.0.md",
            (
                "FR-05（可选）",
                "默认首次交付和正式发布使用 Codex Desktop 本机 MCP stdio",
                "FR-05 仅在发布范围启用 remote profile 时成为必需门禁",
                "上游阻塞期间不创建派生任务",
                "默认必需门禁 FR-01、FR-02、FR-03、FR-04、FR-06、FR-07、FR-08、FR-09",
            ),
        ),
        "context-projection-plan.md": (
            PROJECT_ROOT
            / "docs"
            / "CodexSessionManager-v1.1-context-projection-and-sensitive-data-plan.md",
            (
                "2.4 能力状态以 2.4 收口记录为准，研发顺序以本计划为准",
                "上游阻塞期间不得创建派生任务",
            ),
        ),
        "acceptance-index.md": (
            PROJECT_ROOT / "docs" / "acceptance" / "README.md",
            (
                "App Server 操作契约人工审查流程（当前归档/反归档能力依据）",
                "当前文件关系如下：2.4 能力状态以",
                "正式发布前人工验收；上下文应用步骤须按 2.4 收口结论执行，当前不可用",
            ),
        ),
    }
    for name, (path, markers) in expectations.items():
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        assert not missing, (name, missing)


def test_readmes_keep_restore_import_and_trim_commands_plan_only() -> None:
    for name, (path, expected_rows) in README_COMMAND_CONTRACTS.items():
        text = path.read_text(encoding="utf-8")
        command_rows = "\n".join(line for line in text.splitlines() if line.startswith("| `csm "))
        missing = [row for row in expected_rows if row not in command_rows]
        assert not missing, (name, missing)
        assert not any(row in command_rows for row in README_FORBIDDEN_COMMAND_ROWS), name


def test_historical_documents_have_top_superseded_markers() -> None:
    for name, (path, expected_prefix, markers) in HISTORICAL_DOCUMENTS.items():
        text = path.read_text(encoding="utf-8")
        marker, separator, body = text.partition("\n\n")
        assert separator, name
        assert marker.startswith(expected_prefix), name
        assert body.startswith("# "), name
        missing = [expected for expected in markers if expected not in marker]
        assert not missing, (name, missing)


def test_current_docs_do_not_use_exact_profile_as_archive_authorization() -> None:
    current_docs = CURRENT_DOC_PATHS
    forbidden = (
        "protocol_profiles",
        "write_enabled",
        "exact_profile",
        "exact profile",
        "只有版本与 schema 哈希精确命中人工批准画像才开放写入",
        "Writes require an exact version and schema-hash match",
        "exact_profile_match: true",
        "未审计版本",
    )
    for path in current_docs:
        text = path.read_text(encoding="utf-8")
        assert not any(phrase.lower() in text.lower() for phrase in forbidden), path
        assert "execute_purge_plan" not in text
        assert "永久删除独立流程" not in text
        assert "永久删除：独立的" not in text


def test_mcp_has_no_codex_write_executors() -> None:
    mcp_text = (PROJECT_ROOT / "src" / "codex_session_manager" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    assert "execute_archive" not in mcp_text
    assert "execute_unarchive" not in mcp_text


def test_every_documented_skill_command_still_exists_in_cli() -> None:
    documented = _documented_command_paths()
    assert documented == EXPECTED_COMMAND_PATHS

    runner = CliRunner()
    for command_path in sorted(documented):
        result = runner.invoke(app, [*command_path, "--help"])
        assert result.exit_code == 0, (command_path, result.output, result.exception)
