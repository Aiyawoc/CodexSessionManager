"""Small repository-local structural check for the bundled Skill."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def _mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return value


def validate(root: Path) -> None:
    skill_path = root / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    if not isinstance(metadata, dict):
        raise ValueError("Skill frontmatter must be a mapping")
    if metadata.get("name") != root.name:
        raise ValueError("Skill name must match its directory")
    if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
        raise ValueError("Skill description is required")
    if not body.strip():
        raise ValueError("Skill instructions are empty")
    for reference in (root / "references").glob("*.md"):
        if not reference.read_text(encoding="utf-8").strip():
            raise ValueError(f"empty Skill reference: {reference}")
    agent_metadata = _mapping(root / "agents" / "openai.yaml")
    interface = agent_metadata.get("interface")
    if not isinstance(interface, dict) or not interface.get("display_name"):
        raise ValueError("agents/openai.yaml requires interface.display_name")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill", type=Path)
    arguments = parser.parse_args()
    validate(arguments.skill)
    print("Skill valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
