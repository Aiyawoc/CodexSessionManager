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

EXPECTED_COMMAND_PATHS = {
    ("doctor",),
    ("threads", "list"),
    ("threads", "show"),
    ("cleanup", "review"),
    ("cleanup", "plan"),
    ("cleanup", "apply"),
    ("cleanup", "reconcile"),
    ("purge", "plan"),
    ("purge", "apply"),
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
    ("audit", "verify"),
    ("audit", "show"),
    ("gui", "open"),
}


def _documented_command_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for line in COMMANDS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("csm "):
            continue
        tokens = shlex.split(stripped)[1:]
        if tokens[0] == "import":
            paths.add(tuple(tokens[:3]))
        elif tokens[0] in {
            "threads",
            "cleanup",
            "purge",
            "backup",
            "restore",
            "trim",
            "hook",
            "audit",
            "gui",
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


def test_every_documented_skill_command_still_exists_in_cli() -> None:
    documented = _documented_command_paths()
    assert documented == EXPECTED_COMMAND_PATHS

    runner = CliRunner()
    for command_path in sorted(documented):
        result = runner.invoke(app, [*command_path, "--help"])
        assert result.exit_code == 0, (command_path, result.output, result.exception)
