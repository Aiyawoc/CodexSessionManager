#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$CSM_REPO_ROOT"
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/.uv-cache"}
export UV_CACHE_DIR="$CSM_UV_CACHE_DIR"
CSM_CHECK_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-check.XXXXXX")
trap 'rm -rf "$CSM_CHECK_ROOT"' EXIT INT TERM

uv run --locked pyside6-uic src/codex_session_manager/gui/main_window.ui -o "$CSM_CHECK_ROOT/ui_main_window.py"
uv run --locked pyside6-uic src/codex_session_manager/gui/precompact_prompt.ui -o "$CSM_CHECK_ROOT/ui_precompact_prompt.py"
cmp "$CSM_CHECK_ROOT/ui_main_window.py" src/codex_session_manager/gui/ui_main_window.py
cmp "$CSM_CHECK_ROOT/ui_precompact_prompt.py" src/codex_session_manager/gui/ui_precompact_prompt.py
uv run --locked pyside6-rcc src/codex_session_manager/gui/resources.qrc -o "$CSM_CHECK_ROOT/resources_rc.py"
cmp "$CSM_CHECK_ROOT/resources_rc.py" src/codex_session_manager/gui/resources_rc.py
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src/codex_session_manager
QT_QPA_PLATFORM=offscreen uv run --locked pytest
CSM_SKILL_VALIDATOR=${CSM_SKILL_VALIDATOR:-"$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"}
test -f "$CSM_SKILL_VALIDATOR"
uv run --no-project --with pyyaml --python 3.13.14 "$CSM_SKILL_VALIDATOR" skills/manage-codex-sessions
