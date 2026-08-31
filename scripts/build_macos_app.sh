#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "V1 build must run on a real Apple Silicon macOS host" >&2
  exit 1
fi

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$CSM_REPO_ROOT"
CSM_BUNDLE_LOCK="$CSM_REPO_ROOT/build/.bundle-operation.lock"
mkdir -p "$CSM_REPO_ROOT/build"
if ! mkdir "$CSM_BUNDLE_LOCK" 2>/dev/null; then
  echo "another bundle build or acceptance run owns $CSM_BUNDLE_LOCK" >&2
  exit 1
fi
printf '%s\n' "$$" > "$CSM_BUNDLE_LOCK/pid"
CSM_VERSION=$(sed -n 's/^__version__ = "\([0-9][0-9.]*\)"$/\1/p' \
  "$CSM_REPO_ROOT/src/codex_session_manager/version.py")
test -n "$CSM_VERSION"
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/build/.uv-cache"}
export UV_CACHE_DIR="$CSM_UV_CACHE_DIR"
export NUITKA_CACHE_DIR="$CSM_REPO_ROOT/build/.nuitka-cache"
CSM_BUILD_SPEC=$(mktemp "$CSM_REPO_ROOT/.pysidedeploy.macos.XXXXXX.spec")
cp "$CSM_REPO_ROOT/pysidedeploy.spec" "$CSM_BUILD_SPEC"
CSM_BUILD_ENV="$CSM_REPO_ROOT/build/.venv-build"
CSM_NUITKA_CRASH_REPORT="$CSM_REPO_ROOT/nuitka-crash-report.xml"
CSM_NUITKA_REPORT="$CSM_REPO_ROOT/build/nuitka-compilation-report.xml"
CSM_NUITKA_SOURCE="$CSM_BUILD_ENV/lib/python3.13/site-packages/nuitka/build/static_src/HelpersSafeStrings.c"
CSM_NUITKA_BACKUP=""
CSM_PYSIDE_DEPLOY_SOURCE="$CSM_BUILD_ENV/lib/python3.13/site-packages/PySide6/scripts/deploy_lib/__init__.py"
CSM_PYSIDE_DEPLOY_BACKUP=""
restore_build_inputs() {
  if [ -f "$CSM_BUILD_SPEC" ]; then
    rm -f "$CSM_BUILD_SPEC"
  fi
  if [ -n "$CSM_NUITKA_BACKUP" ] && [ -f "$CSM_NUITKA_BACKUP" ]; then
    cp "$CSM_NUITKA_BACKUP" "$CSM_NUITKA_SOURCE"
    rm -f "$CSM_NUITKA_BACKUP"
  fi
  if [ -n "$CSM_PYSIDE_DEPLOY_BACKUP" ] && [ -f "$CSM_PYSIDE_DEPLOY_BACKUP" ]; then
    cp "$CSM_PYSIDE_DEPLOY_BACKUP" "$CSM_PYSIDE_DEPLOY_SOURCE"
    rm -f "$CSM_PYSIDE_DEPLOY_BACKUP"
  fi
}
cleanup_build_operation() {
  restore_build_inputs
  rm -f "$CSM_BUNDLE_LOCK/pid"
  rmdir "$CSM_BUNDLE_LOCK" 2>/dev/null || true
}
trap cleanup_build_operation EXIT INT TERM

"$CSM_REPO_ROOT/scripts/fetch_age_macos_arm64.sh"
"$CSM_REPO_ROOT/scripts/check.sh"
UV_PROJECT_ENVIRONMENT="$CSM_BUILD_ENV" uv sync --locked --no-default-groups \
  --group runtime --group gui --group build --compile-bytecode
test "$(shasum -a 256 "$CSM_NUITKA_SOURCE" | awk '{print $1}')" = \
  "e9bd8b7c8ca6e7c913d6e89cdc1f942a24816fc2f299b79114cbc162ed007211"
CSM_NUITKA_BACKUP=$(mktemp "${TMPDIR:-/tmp}/csm-nuitka-source.XXXXXX")
cp "$CSM_NUITKA_SOURCE" "$CSM_NUITKA_BACKUP"
patch -s -p1 -d "$CSM_BUILD_ENV/lib/python3.13/site-packages/nuitka" \
  < "$CSM_REPO_ROOT/packaging/patches/nuitka-4.0-macos-utf8-path.patch"
test "$(shasum -a 256 "$CSM_PYSIDE_DEPLOY_SOURCE" | awk '{print $1}')" = \
  "8d5ef1e1eeeb6b538f74b134308559e3aca58bb1f920dcf27d637bb935355a38"
CSM_PYSIDE_DEPLOY_BACKUP=$(mktemp "${TMPDIR:-/tmp}/csm-pyside-deploy.XXXXXX")
cp "$CSM_PYSIDE_DEPLOY_SOURCE" "$CSM_PYSIDE_DEPLOY_BACKUP"
patch -s -p1 -d "$CSM_BUILD_ENV/lib/python3.13/site-packages/PySide6" \
  < "$CSM_REPO_ROOT/packaging/patches/pyside6-6.11.1-deploy-ignore-virtualenvs.patch"
"$CSM_REPO_ROOT/scripts/build_icon_macos.sh"
rm -rf "$CSM_REPO_ROOT/deployment" "$CSM_REPO_ROOT/dist/CodexSessionManager.app"
rm -f "$CSM_NUITKA_CRASH_REPORT" "$CSM_NUITKA_REPORT"
PATH="$CSM_BUILD_ENV/bin:$PATH" "$CSM_BUILD_ENV/bin/pyside6-deploy" \
  -c "$CSM_BUILD_SPEC" --force --mode standalone \
  --extra-ignore-dirs=.venv,.venv-build,.uv-cache,.nuitka-cache,build,dist,deployment,vendor,artifacts
if [ -f "$CSM_NUITKA_CRASH_REPORT" ]; then
  echo "Nuitka emitted a crash report; refusing a partial or stale app bundle" >&2
  exit 1
fi
test -f "$CSM_NUITKA_REPORT"
sed -n '2p' "$CSM_NUITKA_REPORT" | grep -q 'completion="yes"'
restore_build_inputs

CSM_APP="$CSM_REPO_ROOT/dist/CodexSessionManager.app"
if [ -x "$CSM_APP/Contents/MacOS/app_entry" ]; then
  mv "$CSM_APP/Contents/MacOS/app_entry" "$CSM_APP/Contents/MacOS/CodexSessionManager"
  /usr/libexec/PlistBuddy -c "Set :CFBundleExecutable CodexSessionManager" "$CSM_APP/Contents/Info.plist"
fi
test -x "$CSM_APP/Contents/MacOS/CodexSessionManager"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName CodexSessionManager" "$CSM_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName CodexSessionManager" "$CSM_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.codex-session-manager.app" "$CSM_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $CSM_VERSION" "$CSM_APP/Contents/Info.plist"
mkdir -p "$CSM_APP/Contents/Resources/bin" "$CSM_APP/Contents/Resources/licenses" \
  "$CSM_APP/Contents/Resources/skills"
install -m 0755 "$CSM_REPO_ROOT/vendor/age/age" "$CSM_APP/Contents/Resources/bin/age"
install -m 0755 "$CSM_REPO_ROOT/vendor/age/age-keygen" \
  "$CSM_APP/Contents/Resources/bin/age-keygen"
ditto "$CSM_REPO_ROOT/skills/manage-codex-sessions" \
  "$CSM_APP/Contents/Resources/skills/manage-codex-sessions"
install -m 0644 "$CSM_REPO_ROOT/vendor/age/LICENSE" "$CSM_APP/Contents/Resources/licenses/age-BSD-3-Clause.txt"
install -m 0644 "$CSM_REPO_ROOT/vendor/age/verification.json" "$CSM_APP/Contents/Resources/licenses/age-verification.json"
install -m 0644 "$CSM_REPO_ROOT/THIRD_PARTY_NOTICES.md" "$CSM_APP/Contents/Resources/licenses/THIRD_PARTY_NOTICES.md"
install -m 0644 "$CSM_REPO_ROOT/packaging/patches/nuitka-4.0-macos-utf8-path.patch" \
  "$CSM_APP/Contents/Resources/licenses/nuitka-4.0-macos-utf8-path.patch"
install -m 0644 "$CSM_REPO_ROOT/packaging/patches/pyside6-6.11.1-deploy-ignore-virtualenvs.patch" \
  "$CSM_APP/Contents/Resources/licenses/pyside6-6.11.1-deploy-ignore-virtualenvs.patch"
install -m 0644 "$CSM_BUILD_ENV/lib/python3.13/site-packages/nuitka-4.0.dist-info/licenses/LICENSE.txt" \
  "$CSM_APP/Contents/Resources/licenses/nuitka-GPLv3.txt"
install -m 0644 "$CSM_BUILD_ENV/lib/python3.13/site-packages/nuitka-4.0.dist-info/licenses/LICENSE-RUNTIME.txt" \
  "$CSM_APP/Contents/Resources/licenses/nuitka-runtime-exception.txt"

if [ -n "${CSM_DEVELOPER_ID:-}" ]; then
  printf '%s\n' "developer-id" > "$CSM_APP/Contents/Resources/build-channel"
  codesign --force --deep --options runtime --timestamp --sign "$CSM_DEVELOPER_ID" "$CSM_APP"
else
  if [ "${CSM_TEST_RELEASE:-0}" = "1" ]; then
    printf '%s\n' "macos-test-adhoc" > "$CSM_APP/Contents/Resources/build-channel"
    install -m 0644 "$CSM_REPO_ROOT/packaging/TEST_RELEASE_NOTICE.txt" \
      "$CSM_APP/Contents/Resources/TEST_RELEASE_NOTICE.txt"
  else
    printf '%s\n' "local-adhoc" > "$CSM_APP/Contents/Resources/build-channel"
  fi
  codesign --force --deep --timestamp=none --sign - "$CSM_APP"
fi
codesign --verify --deep --strict --verbose=2 "$CSM_APP"
CSM_DOCTOR_ROOT="$CSM_REPO_ROOT/build/bundle-doctor"
mkdir -p "$CSM_DOCTOR_ROOT/codex-home"
set -- cli doctor
if [ "${CSM_SKIP_APP_SERVER_ACCEPTANCE:-0}" = "1" ]; then
  set -- "$@" --skip-app-server
fi
CODEX_HOME="$CSM_DOCTOR_ROOT/codex-home" \
  CSM_CODEX_HOME="$CSM_DOCTOR_ROOT/codex-home" \
  CSM_DATA_DIR="$CSM_DOCTOR_ROOT/data" \
  CSM_CONFIG_DIR="$CSM_DOCTOR_ROOT/config" \
  CSM_CACHE_DIR="$CSM_DOCTOR_ROOT/cache" \
  CSM_LOG_DIR="$CSM_DOCTOR_ROOT/log" \
  "$CSM_APP/Contents/MacOS/CodexSessionManager" "$@"

echo "$CSM_APP"
