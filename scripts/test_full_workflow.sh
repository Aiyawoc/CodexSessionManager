#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CSM_REUSE_APP=0
CSM_TEST_APP="$CSM_REPO_ROOT/dist/CodexSessionManager.app"
CSM_REUSE_ROOT=""

cleanup_full_workflow() {
  if [ -n "$CSM_REUSE_ROOT" ]; then
    rm -rf "$CSM_REUSE_ROOT"
  fi
}
trap cleanup_full_workflow EXIT INT TERM

usage() {
  cat >&2 <<'EOF'
usage:
  scripts/test_full_workflow.sh
  scripts/test_full_workflow.sh --reuse-app [APP_PATH]

The default path rebuilds the macOS arm64 app from the current source. The
--reuse-app path is faster but is only a local smoke run of an existing bundle.
EOF
}

case "$#" in
  0) ;;
  1)
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --reuse-app) CSM_REUSE_APP=1 ;;
      *)
        usage
        exit 2
        ;;
    esac
    ;;
  2)
    if [ "$1" != "--reuse-app" ]; then
      usage
      exit 2
    fi
    CSM_REUSE_APP=1
    CSM_TEST_APP=$2
    ;;
  *)
    usage
    exit 2
    ;;
esac

case "$CSM_TEST_APP" in
  /*) ;;
  *) CSM_TEST_APP="$CSM_REPO_ROOT/$CSM_TEST_APP" ;;
esac

if [ "$CSM_REUSE_APP" -eq 1 ]; then
  if [ ! -d "$CSM_TEST_APP" ]; then
    echo "reused app does not exist: $CSM_TEST_APP" >&2
    exit 1
  fi
  CSM_REUSE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-full-reuse.XXXXXX")
  ditto "$CSM_TEST_APP" "$CSM_REUSE_ROOT/CodexSessionManager.app"
  CSM_TEST_APP="$CSM_REUSE_ROOT/CodexSessionManager.app"
  printf '%s\n' '[full 1/4] Run source workflow before reusing an existing bundle'
  "$CSM_REPO_ROOT/scripts/test_source_workflow.sh"
else
  printf '%s\n' '[full 1/4] Build a fresh bundle; the build runs the complete source gate'
  "$CSM_REPO_ROOT/scripts/build_macos_app.sh"
fi

printf '%s\n' '[full 2/4] Accept the standalone bundle with no development runtime on PATH'
"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_TEST_APP"

printf '%s\n' '[full 3/4] Run real age backup, archive, and unarchive lifecycle'
CSM_TEST_AGE_BIN="$CSM_TEST_APP/Contents/Resources/bin/age" \
  UV_CACHE_DIR="${UV_CACHE_DIR:-$CSM_REPO_ROOT/.uv-cache}" \
  uv run --locked pytest -q tests/test_lifecycle_integration.py

printf '%s\n' '[full 4/4] Run install, Skill, and Hook workflows in one isolated fixture'
"$CSM_REPO_ROOT/scripts/test_installed_workflow.sh" "$CSM_TEST_APP" all

printf '%s\n' 'Full automated workflow passed.'
