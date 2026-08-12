#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$CSM_REPO_ROOT"
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/.uv-cache"}
export UV_CACHE_DIR="$CSM_UV_CACHE_DIR"
CSM_SOURCE_TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-source-workflow.XXXXXX")

cleanup_source_workflow() {
  rm -rf "$CSM_SOURCE_TEST_ROOT"
}
trap cleanup_source_workflow EXIT INT TERM

printf '%s\n' '[source 1/3] Sync locked CPython 3.13.14 environment'
uv sync --locked --compile-bytecode

printf '%s\n' '[source 2/3] Run generated-file, shell, lint, type, pytest, GUI, and Skill gates'
"$CSM_REPO_ROOT/scripts/check.sh"

printf '%s\n' '[source 3/3] Smoke-test the installed CLI entry in an empty isolated data root'
mkdir -m 700 -p "$CSM_SOURCE_TEST_ROOT/home" "$CSM_SOURCE_TEST_ROOT/codex-home" \
  "$CSM_SOURCE_TEST_ROOT/data" "$CSM_SOURCE_TEST_ROOT/config" \
  "$CSM_SOURCE_TEST_ROOT/cache" "$CSM_SOURCE_TEST_ROOT/log"
env \
  HOME="$CSM_SOURCE_TEST_ROOT/home" \
  CODEX_HOME="$CSM_SOURCE_TEST_ROOT/codex-home" \
  CSM_CODEX_HOME="$CSM_SOURCE_TEST_ROOT/codex-home" \
  CSM_DATA_DIR="$CSM_SOURCE_TEST_ROOT/data" \
  CSM_CONFIG_DIR="$CSM_SOURCE_TEST_ROOT/config" \
  CSM_CACHE_DIR="$CSM_SOURCE_TEST_ROOT/cache" \
  CSM_LOG_DIR="$CSM_SOURCE_TEST_ROOT/log" \
  uv run --locked csm doctor --skip-app-server

printf '%s\n' 'Source workflow passed.'
