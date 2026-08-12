#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "age bundle fetch requires darwin-arm64" >&2
  exit 1
fi

AGE_VERSION="1.3.1"
AGE_ARCHIVE="age-v${AGE_VERSION}-darwin-arm64.tar.gz"
AGE_PROOF="${AGE_ARCHIVE}.proof"
AGE_ARCHIVE_SHA="01120ea2cbf0463d4c6bd767f99f3271bbed1cdc8a9aa718a76ba1fe4f01998b"
AGE_PROOF_SHA="e53545de98acd8fb17aca18ab4940e46edd032418df352b7387be4bc5379a0ac"
AGE_BINARY_SHA="0e3ea0b1bed2b30aa2dc46eef4e1723864d626c80f37319c20d9b73ca045f56f"
AGE_BASE_URL="https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}"
CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_FETCH_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-age.XXXXXX")
trap 'chmod -R u+w "$CSM_FETCH_ROOT" 2>/dev/null || true; rm -rf "$CSM_FETCH_ROOT"' EXIT INT TERM

curl --fail --location --proto '=https' --tlsv1.2 \
  --output "$CSM_FETCH_ROOT/$AGE_ARCHIVE" "$AGE_BASE_URL/$AGE_ARCHIVE"
curl --fail --location --proto '=https' --tlsv1.2 \
  --output "$CSM_FETCH_ROOT/$AGE_PROOF" "$AGE_BASE_URL/$AGE_PROOF"

printf '%s  %s\n' "$AGE_ARCHIVE_SHA" "$CSM_FETCH_ROOT/$AGE_ARCHIVE" | shasum -a 256 -c -
printf '%s  %s\n' "$AGE_PROOF_SHA" "$CSM_FETCH_ROOT/$AGE_PROOF" | shasum -a 256 -c -

mkdir -p "$CSM_FETCH_ROOT/bin"
cp "$CSM_REPO_ROOT/packaging/age-sigsum-keys.pub" "$CSM_FETCH_ROOT/age-sigsum-key.pub"
GOCACHE="$CSM_FETCH_ROOT/go-cache" \
  GOPATH="$CSM_FETCH_ROOT/go-path" \
  GOBIN="$CSM_FETCH_ROOT/bin" \
  go install sigsum.org/sigsum-go/cmd/sigsum-verify@v0.13.1
"$CSM_FETCH_ROOT/bin/sigsum-verify" \
  -k "$CSM_FETCH_ROOT/age-sigsum-key.pub" \
  -P sigsum-generic-2025-1 \
  "$CSM_FETCH_ROOT/$AGE_PROOF" < "$CSM_FETCH_ROOT/$AGE_ARCHIVE"

mkdir -p "$CSM_FETCH_ROOT/extracted"
tar -xzf "$CSM_FETCH_ROOT/$AGE_ARCHIVE" -C "$CSM_FETCH_ROOT/extracted"
test -x "$CSM_FETCH_ROOT/extracted/age/age"
test -f "$CSM_FETCH_ROOT/extracted/age/LICENSE"
printf '%s  %s\n' "$AGE_BINARY_SHA" "$CSM_FETCH_ROOT/extracted/age/age" | shasum -a 256 -c -

mkdir -p "$CSM_REPO_ROOT/vendor/age"
install -m 0755 "$CSM_FETCH_ROOT/extracted/age/age" "$CSM_REPO_ROOT/vendor/age/age"
install -m 0644 "$CSM_FETCH_ROOT/extracted/age/LICENSE" "$CSM_REPO_ROOT/vendor/age/LICENSE"
install -m 0644 "$CSM_REPO_ROOT/packaging/age-v1.3.1.json" "$CSM_REPO_ROOT/vendor/age/verification.json"
"$CSM_REPO_ROOT/vendor/age/age" --version
