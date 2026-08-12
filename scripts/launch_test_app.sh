#!/bin/sh
set -eu

# Launch the app installed by scripts/install_test_app.sh inside its isolated
# HOME.  The explicit environment prevents the test app from reading or
# writing the real user's Codex home and configuration.

CSM_TEST_ROOT=${1:-${CSM_TEST_ROOT:-}}

usage() {
  cat >&2 <<'EOF'
用法:
  scripts/launch_test_app.sh /absolute/path/to/csm-codex-home-test

也可以通过 CSM_TEST_ROOT 环境变量指定测试根目录。
EOF
}

if [ "$#" -gt 1 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  [ "$#" -le 1 ] && exit 0
  exit 2
fi

if [ -z "$CSM_TEST_ROOT" ]; then
  usage
  exit 2
fi

case "$CSM_TEST_ROOT" in
  /*) ;;
  *)
    echo "error: TEST_ROOT must be an absolute path: $CSM_TEST_ROOT" >&2
    exit 2
    ;;
esac

CSM_TEST_HOME="$CSM_TEST_ROOT/home"
CSM_TEST_CODEX_HOME="$CSM_TEST_ROOT/codex-home"
CSM_TEST_EXECUTABLE="$CSM_TEST_HOME/Applications/CodexSessionManager.app/Contents/MacOS/CodexSessionManager"
CSM_SYSTEM_PATH=/usr/bin:/bin:/usr/sbin:/sbin

# Resolve the host Codex CLI before switching to the minimal test PATH.  A
# Node-installed Codex CLI also needs its sibling `node` directory on PATH.
CSM_TEST_CODEX_BIN=${CSM_CODEX_BIN:-}
if [ -n "$CSM_TEST_CODEX_BIN" ] && [ "${CSM_TEST_CODEX_BIN#/}" = "$CSM_TEST_CODEX_BIN" ]; then
  CSM_TEST_CODEX_BIN=$(command -v "$CSM_TEST_CODEX_BIN" || true)
fi
if [ -z "$CSM_TEST_CODEX_BIN" ]; then
  CSM_TEST_CODEX_BIN=$(command -v codex || true)
fi
CSM_TEST_PATH="$CSM_SYSTEM_PATH"
if [ -n "$CSM_TEST_CODEX_BIN" ]; then
  CSM_TEST_CODEX_BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$CSM_TEST_CODEX_BIN")" && pwd -P)
  CSM_TEST_PATH="$CSM_TEST_CODEX_BIN_DIR:$CSM_SYSTEM_PATH"
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: this script requires macOS" >&2
  exit 1
fi

if [ ! -x "$CSM_TEST_EXECUTABLE" ]; then
  echo "error: test App not found or not executable: $CSM_TEST_EXECUTABLE" >&2
  echo "       install it first with scripts/install_test_app.sh" >&2
  exit 1
fi

if [ -n "$CSM_TEST_CODEX_BIN" ]; then
  exec env \
    HOME="$CSM_TEST_HOME" \
    PATH="$CSM_TEST_PATH" \
    CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_BIN="$CSM_TEST_CODEX_BIN" \
    CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
    CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
    CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
    CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
    "$CSM_TEST_EXECUTABLE"
fi

exec env \
  HOME="$CSM_TEST_HOME" \
  PATH="$CSM_TEST_PATH" \
  CODEX_HOME="$CSM_TEST_CODEX_HOME" \
  CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
  CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
  CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
  CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
  CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
  "$CSM_TEST_EXECUTABLE"
