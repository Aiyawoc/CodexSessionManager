#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_EVIDENCE_DIR="$CSM_REPO_ROOT/build/first-delivery-acceptance"
CSM_APP=""

usage() {
  cat <<'EOF'
Usage: scripts/accept_first_delivery.sh [--evidence-dir DIR] [--app APP]

Without --app, run the complete source/offscreen first-delivery gate.
With --app, also validate the macOS bundle and require its bundled age binary.
Evidence files are immutable and the destination directory must be empty.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --evidence-dir)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      CSM_EVIDENCE_DIR=$2
      shift 2
      ;;
    --app)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      CSM_APP=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$CSM_REPO_ROOT"

if [ -e "$CSM_EVIDENCE_DIR" ] && [ -n "$(find "$CSM_EVIDENCE_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  echo "evidence directory must be empty: $CSM_EVIDENCE_DIR" >&2
  exit 1
fi
mkdir -p "$CSM_EVIDENCE_DIR"

if [ ! -x "$CSM_REPO_ROOT/.venv/bin/csm" ]; then
  echo "source environment is missing; run uv sync --locked --all-groups first" >&2
  exit 1
fi

"$CSM_REPO_ROOT/scripts/check.sh"

QT_QPA_PLATFORM=offscreen \
  "$CSM_REPO_ROOT/.venv/bin/csm" acceptance run \
  --output "$CSM_EVIDENCE_DIR/source.json" \
  --markdown-output "$CSM_EVIDENCE_DIR/source.md"

if [ -z "$CSM_APP" ]; then
  cat <<EOF
Source first-delivery gate passed.
Evidence: $CSM_EVIDENCE_DIR/source.json

No application bundle was supplied. Build the app, then rerun:
  scripts/accept_first_delivery.sh --evidence-dir NEW_EMPTY_DIR --app /path/to/CodexSessionManager.app
EOF
  exit 0
fi

CSM_APP=$(CDPATH= cd -- "$(dirname -- "$CSM_APP")" && pwd)/$(basename -- "$CSM_APP")
test -d "$CSM_APP"
test -x "$CSM_APP/Contents/MacOS/CodexSessionManager"
test -x "$CSM_APP/Contents/Resources/bin/age"

"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_APP"

CSM_APP_PATH="$CSM_APP" \
CSM_AGE_BIN="$CSM_APP/Contents/Resources/bin/age" \
QT_QPA_PLATFORM=offscreen \
  "$CSM_REPO_ROOT/.venv/bin/csm" acceptance release \
  --output "$CSM_EVIDENCE_DIR/release.json" \
  --markdown-output "$CSM_EVIDENCE_DIR/release.md"

cat <<EOF
First-delivery source and bundle gates passed.
Source evidence:  $CSM_EVIDENCE_DIR/source.json
Release evidence: $CSM_EVIDENCE_DIR/release.json

This does not claim Apple notarization, Windows-native acceptance, or a real
ChatGPT/Cloudflare connector test. Complete the manual runbook before publishing.
EOF
