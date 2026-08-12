#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
exec "$CSM_REPO_ROOT/scripts/test_installed_workflow.sh" \
  "${1:-$CSM_REPO_ROOT/dist/CodexSessionManager.app}" skill
