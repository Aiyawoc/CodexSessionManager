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

CURRENT_CONTRACT_DOCUMENTS = {
    "AGENTS.md": (
        PROJECT_ROOT / "AGENTS.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "README-cn.md": (
        PROJECT_ROOT / "README-cn.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "README.md": (
        PROJECT_ROOT / "README.md",
        (
            "version-independent",
            "contract-sensitive",
            "not archive authorization conditions.",
            "archive and unarchive are evaluated against static, human-reviewed minimal operation contracts.",
        ),
    ),
    "acceptance/README.md": (
        PROJECT_ROOT / "docs" / "acceptance" / "README.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "local-controlled-v1.1.0.md": (
        PROJECT_ROOT / "docs" / "acceptance" / "local-controlled-v1.1.0.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "静态、人工复核的最小操作契约",
        ),
    ),
    "context-projection-plan.md": (
        PROJECT_ROOT
        / "docs"
        / "CodexSessionManager-v1.1-context-projection-and-sensitive-data-plan.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "phase-two-plan.md": (
        PROJECT_ROOT / "docs" / "CodexSessionManager 二期最终实施计划.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "SKILL.md": (
        SKILL_PATH,
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
        ),
    ),
    "safety.md": (
        SKILL_ROOT / "references" / "safety.md",
        (
            "版本无关",
            "契约敏感",
            "不是归档授权条件",
            "归档与反归档由静态、人工复核的最小操作契约逐项评估",
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
    COMMANDS_PATH,
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
    ("restore", "apply"),
    ("import", "chatgpt", "plan"),
    ("import", "chatgpt", "apply"),
    ("import", "codex", "plan"),
    ("import", "codex", "apply"),
    ("trim", "review"),
    ("trim", "suggest"),
    ("trim", "apply"),
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


def test_current_boundaries_keep_unavailable_writes_and_mcp_read_only() -> None:
    current_docs = [
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "README-cn.md",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "acceptance" / "README.md",
        PROJECT_ROOT / "docs" / "acceptance" / "first-delivery-v1.1.0.md",
        PROJECT_ROOT / "docs" / "acceptance" / "formal-release-manual-v1.1.0.md",
        PROJECT_ROOT / "docs" / "acceptance" / "local-controlled-v1.1.0.md",
        PROJECT_ROOT / "docs" / "releases" / "v1.1.0-first-delivery.md",
        SKILL_PATH,
        SKILL_ROOT / "references" / "safety.md",
        SKILL_ROOT / "references" / "commands.md",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in current_docs)
    assert "第一版任务管理只提供盘点、备份、批量归档和反归档" in joined
    assert "原任务应用不可用" in joined
    assert "永久删除" in joined and "不可用" in joined
    assert "archive/unarchive executors" in joined
    assert "execute_archive" not in joined
    assert "execute_unarchive" not in joined
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
