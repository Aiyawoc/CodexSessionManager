#!/bin/sh
set -eu

# Install the app under an isolated HOME while using a copy of the current
# Codex home.  The test root is intentionally kept after the script exits so
# that the caller can inspect it and launch the app manually.

CSM_PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CSM_SOURCE_APP=${1:-"$CSM_PROJECT_ROOT/dist/CodexSessionManager.app"}
CSM_TEST_ROOT=${2:-"${CSM_TEST_ROOT:-}"}
CSM_SOURCE_CODEX_HOME=${CSM_SOURCE_CODEX_HOME:-${CODEX_HOME:-"$HOME/.codex"}}
CSM_OPEN_TEST_APP=${CSM_OPEN_TEST_APP:-0}

usage() {
  cat >&2 <<'EOF'
用法:
  scripts/install_test_app.sh [APP_PATH] [TEST_ROOT]

默认值:
  APP_PATH   ./dist/CodexSessionManager.app
  TEST_ROOT  自动创建于系统临时目录
  源 Codex 目录由 CSM_SOURCE_CODEX_HOME、CODEX_HOME 或 ~/.codex 决定

环境变量:
  CSM_SOURCE_CODEX_HOME  指定要复制的 Codex home
  CSM_OPEN_TEST_APP=1    安装完成后打开测试 App
EOF
}

if [ "$#" -eq 1 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
  usage
  exit 0
fi

if [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: this script requires macOS" >&2
  exit 1
fi

for CSM_REQUIRED_TOOL in ditto codesign install; do
  if ! command -v "$CSM_REQUIRED_TOOL" >/dev/null 2>&1; then
    echo "error: required command not found: $CSM_REQUIRED_TOOL" >&2
    exit 1
  fi
done

if [ ! -d "$CSM_SOURCE_APP" ] || [ ! -x "$CSM_SOURCE_APP/Contents/MacOS/CodexSessionManager" ]; then
  echo "error: app not found or incomplete: $CSM_SOURCE_APP" >&2
  echo "       build it first with scripts/build_macos_app.sh" >&2
  exit 1
fi

if [ ! -d "$CSM_SOURCE_CODEX_HOME" ]; then
  echo "error: Codex home not found: $CSM_SOURCE_CODEX_HOME" >&2
  exit 1
fi

CSM_SOURCE_CODEX_HOME=$(CDPATH= cd -- "$CSM_SOURCE_CODEX_HOME" && pwd -P)

if [ -z "$CSM_TEST_ROOT" ]; then
  CSM_TEST_ROOT=$(mktemp -d "${TMPDIR:-/private/tmp}/csm-codex-home-test.XXXXXX")
else
  case "$CSM_TEST_ROOT" in
    /*) ;;
    *) CSM_TEST_ROOT="$CSM_PROJECT_ROOT/$CSM_TEST_ROOT" ;;
  esac
  if [ -e "$CSM_TEST_ROOT" ]; then
    if [ ! -d "$CSM_TEST_ROOT" ]; then
      echo "error: test root is not a directory: $CSM_TEST_ROOT" >&2
      exit 1
    fi
    if [ -n "$(find "$CSM_TEST_ROOT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
      echo "error: test root is not empty: $CSM_TEST_ROOT" >&2
      echo "       choose a new path; existing test data is never overwritten" >&2
      exit 1
    fi
  else
    mkdir -p "$CSM_TEST_ROOT"
  fi
  CSM_TEST_ROOT=$(CDPATH= cd -- "$CSM_TEST_ROOT" && pwd -P)
fi

case "$CSM_TEST_ROOT/" in
  "$CSM_SOURCE_CODEX_HOME/"*)
    echo "error: test root cannot be inside the source Codex home" >&2
    exit 1
    ;;
esac

umask 077
chmod 700 "$CSM_TEST_ROOT"
CSM_TEST_HOME="$CSM_TEST_ROOT/home"
CSM_TEST_CODEX_HOME="$CSM_TEST_ROOT/codex-home"
CSM_TEST_APP="$CSM_TEST_HOME/Applications/CodexSessionManager.app"
CSM_TEST_LAUNCHER="$CSM_TEST_HOME/.local/bin/csm"
CSM_TEST_COPY="$CSM_TEST_ROOT/.codex-home.$$.partial"
CSM_SYSTEM_PATH=/usr/bin:/bin:/usr/sbin:/sbin

mkdir -m 700 -p "$CSM_TEST_HOME" "$CSM_TEST_ROOT/data" \
  "$CSM_TEST_ROOT/config" "$CSM_TEST_ROOT/cache" "$CSM_TEST_ROOT/log"

echo "复制 Codex home: $CSM_SOURCE_CODEX_HOME"
echo "目标 Codex home: $CSM_TEST_CODEX_HOME"
ditto "$CSM_SOURCE_CODEX_HOME" "$CSM_TEST_COPY"
mv "$CSM_TEST_COPY" "$CSM_TEST_CODEX_HOME"

echo "安装测试 App: $CSM_SOURCE_APP"
HOME="$CSM_TEST_HOME" \
PATH="$CSM_SYSTEM_PATH" \
CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_INSTALL_SKIP_APP_SERVER=1 \
CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
  "$CSM_PROJECT_ROOT/scripts/install_user.sh" "$CSM_SOURCE_APP"

echo "验证测试安装"
HOME="$CSM_TEST_HOME" \
PATH="$CSM_SYSTEM_PATH" \
CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
  "$CSM_TEST_LAUNCHER" doctor --skip-app-server

if [ "$CSM_OPEN_TEST_APP" = "1" ]; then
  open "$CSM_TEST_APP"
fi

cat <<EOF

测试安装完成：
  TEST_ROOT=$CSM_TEST_ROOT
  HOME=$CSM_TEST_HOME
  CODEX_HOME=$CSM_TEST_CODEX_HOME
  APP=$CSM_TEST_APP
  LAUNCHER=$CSM_TEST_LAUNCHER

启动 GUI：
  open "$CSM_TEST_APP"

在同一测试环境运行 CLI：
  HOME="$CSM_TEST_HOME" CODEX_HOME="$CSM_TEST_CODEX_HOME" CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \\
  CSM_DATA_DIR="$CSM_TEST_ROOT/data" CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \\
  CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" CSM_LOG_DIR="$CSM_TEST_ROOT/log" \\
  "$CSM_TEST_LAUNCHER" threads list

注意：测试目录包含当前 Codex home 的副本，可能含认证信息；测试结束后请只删除上面的 TEST_ROOT。
EOF
