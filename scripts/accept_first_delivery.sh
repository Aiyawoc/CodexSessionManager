#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_EVIDENCE_DIR="$CSM_REPO_ROOT/build/first-delivery-acceptance"
CSM_APP=""
CSM_STABLE_APP=""

usage() {
  cat <<'EOF'
Usage: scripts/accept_first_delivery.sh [--evidence-dir DIR] [--app APP] [--stable-app APP]

Without --app, run the complete source/offscreen first-delivery gate.
With --app, also validate the candidate macOS bundle, a separate stable
installation, and the candidate's bundled age binary.
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
    --stable-app)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      CSM_STABLE_APP=$2
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
if [ -z "$CSM_STABLE_APP" ]; then
  CSM_STABLE_APP="${HOME:?}/Applications/CodexSessionManager.app"
fi
CSM_STABLE_APP=$(CDPATH= cd -- "$(dirname -- "$CSM_STABLE_APP")" && pwd)/$(basename -- "$CSM_STABLE_APP")
test -d "$CSM_APP"
test -x "$CSM_APP/Contents/MacOS/CodexSessionManager"
test -x "$CSM_APP/Contents/Resources/bin/age"
test -d "$CSM_STABLE_APP"
test -x "$CSM_STABLE_APP/Contents/MacOS/CodexSessionManager"

if [ "$CSM_APP" = "$CSM_STABLE_APP" ]; then
  echo "candidate and stable app must be separate paths" >&2
  exit 1
fi

CSM_CANDIDATE_VERSION=$("$CSM_APP/Contents/MacOS/CodexSessionManager" cli version)
CSM_STABLE_VERSION=$("$CSM_STABLE_APP/Contents/MacOS/CodexSessionManager" cli version)
test "$CSM_CANDIDATE_VERSION" = "$CSM_STABLE_VERSION"
CSM_CANDIDATE_CHANNEL=$(tr -d '\r\n' < "$CSM_APP/Contents/Resources/build-channel")
CSM_STABLE_CHANNEL=$(tr -d '\r\n' < "$CSM_STABLE_APP/Contents/Resources/build-channel")
test "$CSM_CANDIDATE_CHANNEL" = "$CSM_STABLE_CHANNEL"
CSM_CANDIDATE_EXECUTABLE_SHA256=$(shasum -a 256 \
  "$CSM_APP/Contents/MacOS/CodexSessionManager" | awk '{print $1}')
CSM_STABLE_EXECUTABLE_SHA256=$(shasum -a 256 \
  "$CSM_STABLE_APP/Contents/MacOS/CodexSessionManager" | awk '{print $1}')
test "$CSM_CANDIDATE_EXECUTABLE_SHA256" = "$CSM_STABLE_EXECUTABLE_SHA256"

"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_APP"
"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_STABLE_APP"

CSM_BINDING_TMP=$(mktemp "$CSM_EVIDENCE_DIR/.bundle-binding.XXXXXX")
cleanup_binding() {
  rm -f "$CSM_BINDING_TMP"
}
trap cleanup_binding EXIT INT TERM
{
  printf '%s\n' "candidate_version=$CSM_CANDIDATE_VERSION"
  printf '%s\n' "stable_version=$CSM_STABLE_VERSION"
  printf '%s\n' "candidate_channel=$CSM_CANDIDATE_CHANNEL"
  printf '%s\n' "stable_channel=$CSM_STABLE_CHANNEL"
  printf '%s\n' "candidate_executable_sha256=$CSM_CANDIDATE_EXECUTABLE_SHA256"
  printf '%s\n' "stable_executable_sha256=$CSM_STABLE_EXECUTABLE_SHA256"
} > "$CSM_BINDING_TMP"
mv "$CSM_BINDING_TMP" "$CSM_EVIDENCE_DIR/bundle-binding.txt"
trap - EXIT INT TERM

CSM_APP_PATH="$CSM_STABLE_APP" \
CSM_AGE_BIN="$CSM_APP/Contents/Resources/bin/age" \
QT_QPA_PLATFORM=offscreen \
  "$CSM_REPO_ROOT/.venv/bin/csm" acceptance release \
  --output "$CSM_EVIDENCE_DIR/release.json" \
  --markdown-output "$CSM_EVIDENCE_DIR/release.md"

cat <<EOF
First-delivery source and bundle gates passed.
Source evidence:  $CSM_EVIDENCE_DIR/source.json
Release evidence: $CSM_EVIDENCE_DIR/release.json
Bundle binding:   $CSM_EVIDENCE_DIR/bundle-binding.txt

This does not claim Codex desktop's target-machine MCP/GUI acceptance, Apple
notarization, or Windows-native acceptance. Complete the manual runbook before
publishing.
EOF
