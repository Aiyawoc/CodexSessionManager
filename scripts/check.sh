#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$CSM_REPO_ROOT"
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/.uv-cache"}
export UV_CACHE_DIR="$CSM_UV_CACHE_DIR"
CSM_CHECK_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-check.XXXXXX")
trap 'rm -rf "$CSM_CHECK_ROOT"' EXIT INT TERM

for CSM_SHELL_SCRIPT in scripts/*.sh packaging/csm-launcher; do
  test -x "$CSM_SHELL_SCRIPT"
  sh -n "$CSM_SHELL_SCRIPT"
done
uv run --locked pyside6-uic src/codex_session_manager/gui/main_window.ui -o "$CSM_CHECK_ROOT/ui_main_window.py"
uv run --locked pyside6-uic src/codex_session_manager/gui/precompact_prompt.ui -o "$CSM_CHECK_ROOT/ui_precompact_prompt.py"
cmp "$CSM_CHECK_ROOT/ui_main_window.py" src/codex_session_manager/gui/ui_main_window.py
cmp "$CSM_CHECK_ROOT/ui_precompact_prompt.py" src/codex_session_manager/gui/ui_precompact_prompt.py
uv run --locked pyside6-rcc src/codex_session_manager/gui/resources.qrc -o "$CSM_CHECK_ROOT/resources_rc.py"
# RCC v3 embeds checkout-dependent source mtimes in qt_resource_struct. Compare
# names, payloads, and tree records while ignoring only those timestamp bytes.
uv run --locked python scripts/compare_qt_resources.py \
  "$CSM_CHECK_ROOT/resources_rc.py" src/codex_session_manager/gui/resources_rc.py
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src/codex_session_manager
QT_QPA_PLATFORM=offscreen uv run --locked pytest
CSM_SKILL_VALIDATOR=${CSM_SKILL_VALIDATOR:-"$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"}
uv run --no-project --with pyyaml --python 3.13.14 \
  python scripts/validate_skill.py skills/manage-codex-sessions
if [ -f "$CSM_SKILL_VALIDATOR" ]; then
  uv run --no-project --with pyyaml --python 3.13.14 \
    "$CSM_SKILL_VALIDATOR" skills/manage-codex-sessions
fi
