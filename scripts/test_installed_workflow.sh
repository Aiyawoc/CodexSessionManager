#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CSM_SOURCE_APP=${1:-"$CSM_REPO_ROOT/dist/CodexSessionManager.app"}
CSM_TEST_PHASE=${2:-all}
CSM_SYSTEM_PATH=/usr/bin:/bin:/usr/sbin:/sbin

usage() {
  cat >&2 <<'EOF'
usage: scripts/test_installed_workflow.sh [APP_PATH] [install|skill|hook|all]

Runs against a generated empty HOME and CODEX_HOME. It never copies the real
Codex home. Set CSM_KEEP_TEST_ROOT=1 to retain the temporary fixture on exit.
EOF
}

if [ "$#" -gt 2 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  [ "$#" -le 1 ] && exit 0
  exit 2
fi

case "$CSM_TEST_PHASE" in
  install | skill | hook | all) ;;
  *)
    usage
    exit 2
    ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
  echo 'error: installed workflow requires macOS' >&2
  exit 1
fi

case "$CSM_SOURCE_APP" in
  /*) ;;
  *) CSM_SOURCE_APP="$CSM_REPO_ROOT/$CSM_SOURCE_APP" ;;
esac
if [ ! -d "$CSM_SOURCE_APP" ] || \
  [ ! -x "$CSM_SOURCE_APP/Contents/MacOS/CodexSessionManager" ]; then
  echo "error: app not found or incomplete: $CSM_SOURCE_APP" >&2
  exit 1
fi

for CSM_REQUIRED_TOOL in codesign ditto diff grep install readlink stat uv; do
  if ! command -v "$CSM_REQUIRED_TOOL" >/dev/null 2>&1; then
    echo "error: required command not found: $CSM_REQUIRED_TOOL" >&2
    exit 1
  fi
done

CSM_WORKFLOW_ROOT=$(mktemp -d "${TMPDIR:-/private/tmp}/CSM 自动化 中文.XXXXXX")
CSM_WORKFLOW_ROOT=$(CDPATH= cd -- "$CSM_WORKFLOW_ROOT" && pwd -P)
CSM_TEST_HOME="$CSM_WORKFLOW_ROOT/home"
CSM_TEST_CODEX_HOME="$CSM_WORKFLOW_ROOT/codex-home"
CSM_TEST_DATA_DIR="$CSM_WORKFLOW_ROOT/data"
CSM_TEST_CONFIG_DIR="$CSM_WORKFLOW_ROOT/config"
CSM_TEST_CACHE_DIR="$CSM_WORKFLOW_ROOT/cache"
CSM_TEST_LOG_DIR="$CSM_WORKFLOW_ROOT/log"
CSM_TEST_APP="$CSM_TEST_HOME/Applications/CodexSessionManager.app"
CSM_TEST_EXECUTABLE="$CSM_TEST_APP/Contents/MacOS/CodexSessionManager"
CSM_TEST_LAUNCHER="$CSM_TEST_HOME/.local/bin/csm"
CSM_TEST_SKILL="$CSM_TEST_HOME/.agents/skills/manage-codex-sessions"
CSM_SOURCE_SKILL="$CSM_REPO_ROOT/skills/manage-codex-sessions"
CSM_BUNDLE_SKILL="$CSM_SOURCE_APP/Contents/Resources/skills/manage-codex-sessions"
CSM_SKILL_VALIDATOR=${CSM_SKILL_VALIDATOR:-"$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"}
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/.uv-cache"}
CSM_EXPECTED_VERSION=$(sed -n 's/^__version__ = "\([0-9][0-9.]*\)"$/\1/p' \
  "$CSM_REPO_ROOT/src/codex_session_manager/version.py")
if [ -z "$CSM_EXPECTED_VERSION" ]; then
  echo 'error: unable to read the source version' >&2
  exit 1
fi

cleanup_installed_workflow() {
  if [ "${CSM_KEEP_TEST_ROOT:-0}" = "1" ]; then
    printf '%s\n' "Retained installed-workflow fixture: $CSM_WORKFLOW_ROOT"
  else
    rm -rf "$CSM_WORKFLOW_ROOT"
  fi
}
trap cleanup_installed_workflow EXIT INT TERM

umask 077
mkdir -m 700 -p "$CSM_TEST_HOME" "$CSM_TEST_CODEX_HOME" "$CSM_TEST_DATA_DIR" \
  "$CSM_TEST_CONFIG_DIR" "$CSM_TEST_CACHE_DIR" "$CSM_TEST_LOG_DIR"

run_installer() {
  env \
    HOME="$CSM_TEST_HOME" \
    PATH="$CSM_SYSTEM_PATH" \
    CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_INSTALL_SKIP_APP_SERVER=1 \
    CSM_DATA_DIR="$CSM_TEST_DATA_DIR" \
    CSM_CONFIG_DIR="$CSM_TEST_CONFIG_DIR" \
    CSM_CACHE_DIR="$CSM_TEST_CACHE_DIR" \
    CSM_LOG_DIR="$CSM_TEST_LOG_DIR" \
    "$CSM_REPO_ROOT/scripts/install_user.sh" "$CSM_SOURCE_APP"
}

run_launcher() {
  env \
    HOME="$CSM_TEST_HOME" \
    PATH="$CSM_SYSTEM_PATH" \
    CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_DATA_DIR="$CSM_TEST_DATA_DIR" \
    CSM_CONFIG_DIR="$CSM_TEST_CONFIG_DIR" \
    CSM_CACHE_DIR="$CSM_TEST_CACHE_DIR" \
    CSM_LOG_DIR="$CSM_TEST_LOG_DIR" \
    "$CSM_TEST_LAUNCHER" "$@"
}

run_hook_protocol() {
  CSM_HOOK_MODE=$1
  env \
    HOME="$CSM_TEST_HOME" \
    PATH="$CSM_SYSTEM_PATH" \
    CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_DATA_DIR="$CSM_TEST_DATA_DIR" \
    CSM_CONFIG_DIR="$CSM_TEST_CONFIG_DIR" \
    CSM_CACHE_DIR="$CSM_TEST_CACHE_DIR" \
    CSM_LOG_DIR="$CSM_TEST_LOG_DIR" \
    "$CSM_TEST_EXECUTABLE" hook "$CSM_HOOK_MODE"
}

validate_skill_package() {
  CSM_SKILL_PACKAGE=$1
  UV_CACHE_DIR="$CSM_UV_CACHE_DIR" uv run --locked \
    python "$CSM_REPO_ROOT/scripts/validate_skill.py" "$CSM_SKILL_PACKAGE"
  if [ -f "$CSM_SKILL_VALIDATOR" ]; then
    UV_CACHE_DIR="$CSM_UV_CACHE_DIR" uv run --no-project --with pyyaml --python 3.13.14 \
      "$CSM_SKILL_VALIDATOR" "$CSM_SKILL_PACKAGE"
  fi
}

assert_hook_output() {
  CSM_HOOK_OUTPUT=$1
  CSM_HOOK_STDERR=$2
  CSM_HOOK_LINE_COUNT=$(wc -l < "$CSM_HOOK_OUTPUT" | tr -d '[:space:]')
  test "$CSM_HOOK_LINE_COUNT" = "1"
  grep -Eq '^\{"continue":true(,.*)?\}$' "$CSM_HOOK_OUTPUT"
  test ! -s "$CSM_HOOK_STDERR"
}

test_conflicting_skill_is_preserved() {
  CSM_CONFLICT_ROOT="$CSM_WORKFLOW_ROOT/conflict"
  CSM_CONFLICT_HOME="$CSM_CONFLICT_ROOT/home"
  CSM_CONFLICT_CODEX_HOME="$CSM_CONFLICT_ROOT/codex-home"
  CSM_CONFLICT_SKILL="$CSM_CONFLICT_HOME/.agents/skills/manage-codex-sessions"
  mkdir -m 700 -p "$CSM_CONFLICT_SKILL" "$CSM_CONFLICT_CODEX_HOME"
  printf '%s\n' 'preserve-me' > "$CSM_CONFLICT_SKILL/marker"
  if env \
    HOME="$CSM_CONFLICT_HOME" \
    PATH="$CSM_SYSTEM_PATH" \
    CODEX_HOME="$CSM_CONFLICT_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_CONFLICT_CODEX_HOME" \
    CSM_INSTALL_SKIP_APP_SERVER=1 \
    CSM_DATA_DIR="$CSM_CONFLICT_ROOT/data" \
    CSM_CONFIG_DIR="$CSM_CONFLICT_ROOT/config" \
    CSM_CACHE_DIR="$CSM_CONFLICT_ROOT/cache" \
    CSM_LOG_DIR="$CSM_CONFLICT_ROOT/log" \
    "$CSM_REPO_ROOT/scripts/install_user.sh" "$CSM_SOURCE_APP" \
    >"$CSM_CONFLICT_ROOT/stdout.log" 2>"$CSM_CONFLICT_ROOT/stderr.log"; then
    echo 'error: installer replaced a conflicting Skill path' >&2
    exit 1
  fi
  grep -q 'refusing to replace an existing skill' "$CSM_CONFLICT_ROOT/stderr.log"
  grep -qx 'preserve-me' "$CSM_CONFLICT_SKILL/marker"
  test ! -e "$CSM_CONFLICT_HOME/Applications/CodexSessionManager.app"
}

test_install_phase() {
  printf '%s\n' '[install] Reject a conflicting Skill without modifying it'
  test_conflicting_skill_is_preserved

  printf '%s\n' '[install] Install twice into an empty isolated HOME'
  run_installer > "$CSM_WORKFLOW_ROOT/install-first.log"
  test -d "$CSM_TEST_APP"
  test -x "$CSM_TEST_EXECUTABLE"
  test -x "$CSM_TEST_LAUNCHER"
  test -L "$CSM_TEST_SKILL"
  test "$(readlink "$CSM_TEST_SKILL")" = \
    "$CSM_TEST_APP/Contents/Resources/skills/manage-codex-sessions"
  test ! -e "$CSM_TEST_CODEX_HOME/hooks.json"
  test "$(run_launcher version)" = "$CSM_EXPECTED_VERSION"
  run_launcher doctor --skip-app-server > "$CSM_WORKFLOW_ROOT/installed-doctor.json"
  codesign --verify --deep --strict "$CSM_TEST_APP"

  run_installer > "$CSM_WORKFLOW_ROOT/install-second.log"
  test -d "$CSM_TEST_HOME/Applications/CodexSessionManager.previous.app"
  test -L "$CSM_TEST_SKILL"
  test "$(readlink "$CSM_TEST_SKILL")" = \
    "$CSM_TEST_APP/Contents/Resources/skills/manage-codex-sessions"
  test ! -e "$CSM_TEST_CODEX_HOME/hooks.json"
}

test_skill_phase() {
  printf '%s\n' '[skill] Validate source, bundled, and installed Skill packages'
  test -f "$CSM_SOURCE_SKILL/references/safety.md"
  test -f "$CSM_SOURCE_SKILL/references/commands.md"
  grep -Eq '^[[:space:]]*allow_implicit_invocation:[[:space:]]*false[[:space:]]*$' \
    "$CSM_SOURCE_SKILL/agents/openai.yaml"
  validate_skill_package "$CSM_SOURCE_SKILL"
  validate_skill_package "$CSM_BUNDLE_SKILL"
  validate_skill_package "$CSM_TEST_SKILL"
  diff -qr "$CSM_SOURCE_SKILL" "$CSM_BUNDLE_SKILL"
  diff -qr "$CSM_BUNDLE_SKILL" "$CSM_TEST_SKILL"

  run_launcher --help > "$CSM_WORKFLOW_ROOT/csm-help.txt"
  for CSM_COMMAND in doctor threads cleanup purge backup restore import trim hook audit; do
    grep -q "$CSM_COMMAND" "$CSM_WORKFLOW_ROOT/csm-help.txt"
  done
}

test_hook_phase() {
  printf '%s\n' '[hook] Install into isolated hooks.json and preserve a foreign handler'
  cat > "$CSM_TEST_CODEX_HOME/hooks.json" <<'EOF'
{
  "description": "installed workflow fixture",
  "hooks": {
    "PreCompact": [
      {
        "matcher": "manual",
        "hooks": [
          {"type": "command", "command": "/custom/hook", "timeout": 7}
        ]
      }
    ]
  }
}
EOF
  chmod 600 "$CSM_TEST_CODEX_HOME/hooks.json"
  run_launcher hook status > "$CSM_WORKFLOW_ROOT/hook-status-before.json"
  grep -q '"ready": false' "$CSM_WORKFLOW_ROOT/hook-status-before.json"
  run_launcher hook install --yes > "$CSM_WORKFLOW_ROOT/hook-install.json"
  run_launcher hook status > "$CSM_WORKFLOW_ROOT/hook-status-after.json"
  grep -q '"trust_required": true' "$CSM_WORKFLOW_ROOT/hook-install.json"
  grep -q '"ready": true' "$CSM_WORKFLOW_ROOT/hook-status-after.json"
  grep -Fq '/custom/hook' "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -Fq "$CSM_TEST_EXECUTABLE" "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -Fq 'hook precompact' "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -Fq 'hook postcompact' "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -q '"matcher": "manual|auto"' "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -q '"timeout": 600' "$CSM_TEST_CODEX_HOME/hooks.json"
  grep -q '"timeout": 30' "$CSM_TEST_CODEX_HOME/hooks.json"
  test "$(stat -f '%Lp' "$CSM_TEST_CODEX_HOME/hooks.json")" = "600"
  test -n "$(find "$CSM_TEST_CODEX_HOME" -name 'hooks.json.before-csm-*' -print -quit)"

  printf '%s\n' '[hook] Verify one-line fail-open protocol output'
  printf '%s\n' '{}' | run_hook_protocol precompact \
    > "$CSM_WORKFLOW_ROOT/precompact.json" 2> "$CSM_WORKFLOW_ROOT/precompact.stderr"
  assert_hook_output "$CSM_WORKFLOW_ROOT/precompact.json" \
    "$CSM_WORKFLOW_ROOT/precompact.stderr"

  printf '%s\n' \
    '{"session_id":"workflow","transcript_path":null,"cwd":"/tmp","hook_event_name":"PostCompact","model":"test","turn_id":"turn","trigger":"manual"}' | \
    run_hook_protocol postcompact \
      > "$CSM_WORKFLOW_ROOT/postcompact.json" 2> "$CSM_WORKFLOW_ROOT/postcompact.stderr"
  assert_hook_output "$CSM_WORKFLOW_ROOT/postcompact.json" \
    "$CSM_WORKFLOW_ROOT/postcompact.stderr"

  printf '%s\n' '{}' | env \
    HOME="$CSM_TEST_HOME" \
    PATH="$CSM_SYSTEM_PATH" \
    CODEX_HOME="$CSM_WORKFLOW_ROOT/codex-a" \
    CSM_CODEX_HOME="$CSM_WORKFLOW_ROOT/codex-b" \
    CSM_DATA_DIR="$CSM_TEST_DATA_DIR" \
    CSM_CONFIG_DIR="$CSM_TEST_CONFIG_DIR" \
    CSM_CACHE_DIR="$CSM_TEST_CACHE_DIR" \
    CSM_LOG_DIR="$CSM_TEST_LOG_DIR" \
    "$CSM_TEST_EXECUTABLE" hook precompact \
    > "$CSM_WORKFLOW_ROOT/mixed-root.json" 2> "$CSM_WORKFLOW_ROOT/mixed-root.stderr"
  assert_hook_output "$CSM_WORKFLOW_ROOT/mixed-root.json" \
    "$CSM_WORKFLOW_ROOT/mixed-root.stderr"

  printf '%s\n' '[hook] Uninstall only CSM handlers'
  run_launcher hook uninstall --yes > "$CSM_WORKFLOW_ROOT/hook-uninstall.json"
  run_launcher hook status > "$CSM_WORKFLOW_ROOT/hook-status-final.json"
  grep -q '"ready": false' "$CSM_WORKFLOW_ROOT/hook-status-final.json"
  grep -Fq '/custom/hook' "$CSM_TEST_CODEX_HOME/hooks.json"
  if grep -Fq 'hook precompact' "$CSM_TEST_CODEX_HOME/hooks.json" || \
    grep -Fq 'hook postcompact' "$CSM_TEST_CODEX_HOME/hooks.json"; then
    echo 'error: CSM Hook handler remained after uninstall' >&2
    exit 1
  fi
  test -f "$CSM_TEST_LOG_DIR/hooks.log"
  test "$(stat -f '%Lp' "$CSM_TEST_LOG_DIR/hooks.log")" = "600"
}

test_install_phase
case "$CSM_TEST_PHASE" in
  install) ;;
  skill) test_skill_phase ;;
  hook) test_hook_phase ;;
  all)
    test_skill_phase
    test_hook_phase
    ;;
esac

printf '%s\n' "Installed workflow passed: $CSM_TEST_PHASE"
