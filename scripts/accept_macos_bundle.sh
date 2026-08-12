#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/CodexSessionManager.app" >&2
  exit 2
fi
CSM_SOURCE_APP=$1
CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_HOLD_VENV="$CSM_REPO_ROOT/.venv.csm-acceptance-hold"
CSM_HOLD_BUILD_ENV="$CSM_REPO_ROOT/.venv-build.csm-acceptance-hold"
CSM_BUILD_ENV="$CSM_REPO_ROOT/build/.venv-build"
CSM_BUNDLE_LOCK="$CSM_REPO_ROOT/build/.bundle-operation.lock"
if [ -e "$CSM_HOLD_VENV" ] || [ -e "$CSM_HOLD_BUILD_ENV" ]; then
  echo "refusing to overwrite an existing acceptance environment hold" >&2
  exit 1
fi
mkdir -p "$CSM_REPO_ROOT/build"
if ! mkdir "$CSM_BUNDLE_LOCK" 2>/dev/null; then
  echo "another bundle build or acceptance run owns $CSM_BUNDLE_LOCK" >&2
  exit 1
fi
printf '%s\n' "$$" > "$CSM_BUNDLE_LOCK/pid"
CSM_ACCEPT_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/CSM 验收 中文.XXXXXX")
CSM_ACCEPT_APP="$CSM_ACCEPT_ROOT/Codex Session Manager.app"
CSM_ACCEPT_HOME="$CSM_ACCEPT_ROOT/home"
CSM_ACCEPT_CODEX_HOME="$CSM_ACCEPT_ROOT/codex-home"
restore_acceptance_environment() {
  if [ -d "$CSM_HOLD_VENV" ]; then
    mv "$CSM_HOLD_VENV" "$CSM_REPO_ROOT/.venv"
  fi
  if [ -d "$CSM_HOLD_BUILD_ENV" ]; then
    mkdir -p "$CSM_REPO_ROOT/build"
    mv "$CSM_HOLD_BUILD_ENV" "$CSM_BUILD_ENV"
  fi
  rm -rf "$CSM_ACCEPT_ROOT"
  rm -f "$CSM_BUNDLE_LOCK/pid"
  rmdir "$CSM_BUNDLE_LOCK" 2>/dev/null || true
}
trap restore_acceptance_environment EXIT INT TERM

mkdir -m 700 -p "$CSM_ACCEPT_HOME" "$CSM_ACCEPT_CODEX_HOME" \
  "$CSM_ACCEPT_ROOT/data" "$CSM_ACCEPT_ROOT/config" \
  "$CSM_ACCEPT_ROOT/cache" "$CSM_ACCEPT_ROOT/log"
ditto "$CSM_SOURCE_APP" "$CSM_ACCEPT_APP"
if [ -d "$CSM_REPO_ROOT/.venv" ]; then
  mv "$CSM_REPO_ROOT/.venv" "$CSM_HOLD_VENV"
fi
if [ -d "$CSM_BUILD_ENV" ]; then
  mv "$CSM_BUILD_ENV" "$CSM_HOLD_BUILD_ENV"
fi

env HOME="$CSM_ACCEPT_HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" CSM_CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" \
  CSM_DATA_DIR="$CSM_ACCEPT_ROOT/data" \
  CSM_CONFIG_DIR="$CSM_ACCEPT_ROOT/config" CSM_CACHE_DIR="$CSM_ACCEPT_ROOT/cache" \
  CSM_LOG_DIR="$CSM_ACCEPT_ROOT/log" \
  "$CSM_ACCEPT_APP/Contents/MacOS/CodexSessionManager" cli doctor --skip-app-server
printf '%s\n' '{"session_id":"acceptance","transcript_path":null,"cwd":"/tmp","hook_event_name":"PostCompact","model":"test","turn_id":"turn","trigger":"manual"}' | \
  env HOME="$CSM_ACCEPT_HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" CSM_CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" \
  CSM_DATA_DIR="$CSM_ACCEPT_ROOT/data" \
  CSM_CONFIG_DIR="$CSM_ACCEPT_ROOT/config" CSM_CACHE_DIR="$CSM_ACCEPT_ROOT/cache" \
  CSM_LOG_DIR="$CSM_ACCEPT_ROOT/log" \
  "$CSM_ACCEPT_APP/Contents/MacOS/CodexSessionManager" hook postcompact | \
  /usr/bin/grep -q '"continue":true'
env HOME="$CSM_ACCEPT_HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" CSM_CODEX_HOME="$CSM_ACCEPT_CODEX_HOME" \
  CSM_GUI_SMOKE_EXIT_MS=750 QT_QPA_PLATFORM=offscreen \
  CSM_DATA_DIR="$CSM_ACCEPT_ROOT/data" CSM_CONFIG_DIR="$CSM_ACCEPT_ROOT/config" \
  CSM_CACHE_DIR="$CSM_ACCEPT_ROOT/cache" CSM_LOG_DIR="$CSM_ACCEPT_ROOT/log" \
  "$CSM_ACCEPT_APP/Contents/MacOS/CodexSessionManager"
codesign --verify --deep --strict "$CSM_ACCEPT_APP"
