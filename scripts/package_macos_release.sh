#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_APP=""
CSM_OUTPUT_DIR=""

usage() {
  cat <<'EOF'
Usage: scripts/package_macos_release.sh --app APP [--output-dir DIR]

Validate a macOS application bundle, create a ZIP and SHA-256 file, extract the
archive into a clean temporary directory, and validate the extracted bundle
again. Existing artifacts are never overwritten.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      CSM_APP=$2
      shift 2
      ;;
    --output-dir)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      CSM_OUTPUT_DIR=$2
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

[ -n "$CSM_APP" ] || { usage >&2; exit 2; }
CSM_APP=$(CDPATH= cd -- "$(dirname -- "$CSM_APP")" && pwd)/$(basename -- "$CSM_APP")
CSM_EXECUTABLE="$CSM_APP/Contents/MacOS/CodexSessionManager"
CSM_CHANNEL_FILE="$CSM_APP/Contents/Resources/build-channel"
test -d "$CSM_APP"
test -x "$CSM_EXECUTABLE"
test -f "$CSM_CHANNEL_FILE"

CSM_VERSION=$($CSM_EXECUTABLE cli version)
case "$CSM_VERSION" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *)
    echo "unexpected application version: $CSM_VERSION" >&2
    exit 1
    ;;
esac

CSM_CHANNEL=$(tr -d '\r\n' < "$CSM_CHANNEL_FILE")
case "$CSM_CHANNEL" in
  *test*|*adhoc*) CSM_CHANNEL_SUFFIX="-test" ;;
  release) CSM_CHANNEL_SUFFIX="" ;;
  *)
    echo "unsupported build channel: $CSM_CHANNEL" >&2
    exit 1
    ;;
esac

CSM_ARCHES=$(lipo -archs "$CSM_EXECUTABLE" 2>/dev/null || true)
case "$CSM_ARCHES" in
  "arm64") CSM_ARCH="arm64" ;;
  "x86_64") CSM_ARCH="x86_64" ;;
  "arm64 x86_64"|"x86_64 arm64") CSM_ARCH="universal2" ;;
  *)
    echo "unsupported or unknown application architectures: $CSM_ARCHES" >&2
    exit 1
    ;;
esac

if [ -z "$CSM_OUTPUT_DIR" ]; then
  CSM_OUTPUT_DIR="$CSM_REPO_ROOT/artifacts/v$CSM_VERSION$CSM_CHANNEL_SUFFIX"
fi
CSM_OUTPUT_DIR=$(mkdir -p "$CSM_OUTPUT_DIR" && CDPATH= cd -- "$CSM_OUTPUT_DIR" && pwd)
CSM_BASENAME="CodexSessionManager-macos-$CSM_ARCH-v$CSM_VERSION$CSM_CHANNEL_SUFFIX.zip"
CSM_ZIP="$CSM_OUTPUT_DIR/$CSM_BASENAME"
CSM_CHECKSUM="$CSM_ZIP.sha256"

if [ -e "$CSM_ZIP" ] || [ -e "$CSM_CHECKSUM" ]; then
  echo "refusing to overwrite an existing release artifact" >&2
  echo "$CSM_ZIP" >&2
  echo "$CSM_CHECKSUM" >&2
  exit 1
fi

"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_APP"

CSM_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/csm-package-macos.XXXXXX")
cleanup() {
  rm -rf "$CSM_TEMP"
}
trap cleanup EXIT INT TERM

ditto -c -k --sequesterRsrc --keepParent "$CSM_APP" "$CSM_ZIP"
(
  cd "$CSM_OUTPUT_DIR"
  shasum -a 256 "$CSM_BASENAME" > "$CSM_BASENAME.sha256"
  shasum -a 256 -c "$CSM_BASENAME.sha256"
)

ditto -x -k "$CSM_ZIP" "$CSM_TEMP"
CSM_EXTRACTED_APP="$CSM_TEMP/$(basename -- "$CSM_APP")"
test -d "$CSM_EXTRACTED_APP"
"$CSM_REPO_ROOT/scripts/accept_macos_bundle.sh" "$CSM_EXTRACTED_APP"

CSM_DIGEST=$(awk '{print $1}' "$CSM_CHECKSUM")
cat <<EOF
macOS release artifact created and revalidated.
Version:      $CSM_VERSION
Channel:      $CSM_CHANNEL
Architecture: $CSM_ARCH
ZIP:          $CSM_ZIP
SHA-256:      $CSM_DIGEST
Checksum:     $CSM_CHECKSUM
EOF
