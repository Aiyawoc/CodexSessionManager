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
CSM_SOURCE_CODEX_BIN=${CSM_CODEX_BIN:-}

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

for CSM_REQUIRED_TOOL in ditto pax codesign install; do
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
CSM_TEST_EXECUTABLE="$CSM_TEST_APP/Contents/MacOS/CodexSessionManager"
CSM_TEST_LAUNCHER="$CSM_TEST_HOME/.local/bin/csm"
CSM_TEST_SKILL="$CSM_TEST_HOME/.agents/skills/manage-codex-sessions"
CSM_TEST_LAUNCH_SCRIPT="$CSM_TEST_ROOT/launch-test-app.sh"
CSM_TEST_COPY="$CSM_TEST_ROOT/.codex-home.$$.partial"
CSM_SYSTEM_PATH=/usr/bin:/bin:/usr/sbin:/sbin

# Capture the host Codex CLI before the test launcher switches to its minimal
# PATH.  The generated launcher passes this exact executable to App Server and
# adds its directory so Node-based Codex installations can start.
if [ -n "$CSM_SOURCE_CODEX_BIN" ] && [ "${CSM_SOURCE_CODEX_BIN#/}" = "$CSM_SOURCE_CODEX_BIN" ]; then
  CSM_SOURCE_CODEX_BIN=$(command -v "$CSM_SOURCE_CODEX_BIN" || true)
fi
if [ -z "$CSM_SOURCE_CODEX_BIN" ]; then
  CSM_SOURCE_CODEX_BIN=$(command -v codex || true)
fi
CSM_TEST_PATH="$CSM_SYSTEM_PATH"
if [ -n "$CSM_SOURCE_CODEX_BIN" ]; then
  CSM_SOURCE_CODEX_BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$CSM_SOURCE_CODEX_BIN")" && pwd -P)
  CSM_SOURCE_CODEX_BIN="$CSM_SOURCE_CODEX_BIN_DIR/$(basename -- "$CSM_SOURCE_CODEX_BIN")"
  CSM_TEST_PATH="$CSM_SOURCE_CODEX_BIN_DIR:$CSM_SYSTEM_PATH"
  echo "测试 App Server CLI: $CSM_SOURCE_CODEX_BIN"
else
  echo "警告：未找到 codex CLI；GUI 将无法加载任务列表。" >&2
fi

mkdir -m 700 -p "$CSM_TEST_HOME" "$CSM_TEST_ROOT/data" \
  "$CSM_TEST_ROOT/config" "$CSM_TEST_ROOT/cache" "$CSM_TEST_ROOT/log"

echo "复制 Codex home: $CSM_SOURCE_CODEX_HOME"
echo "目标 Codex home: $CSM_TEST_CODEX_HOME"
echo "跳过 Unix socket 和其他特殊运行时文件"
mkdir -m 700 "$CSM_TEST_COPY"
(
  cd "$CSM_SOURCE_CODEX_HOME"
  find . -mindepth 1 \( -type d -o -type f -o -type l \) -print0 |
    pax -0 -d -rw -pe "$CSM_TEST_COPY"
)
mv "$CSM_TEST_COPY" "$CSM_TEST_CODEX_HOME"

echo "安装测试 App: $CSM_SOURCE_APP"
HOME="$CSM_TEST_HOME" \
PATH="$CSM_TEST_PATH" \
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
PATH="$CSM_TEST_PATH" \
CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
  "$CSM_TEST_LAUNCHER" doctor --skip-app-server
test -L "$CSM_TEST_SKILL"
test -f "$CSM_TEST_SKILL/SKILL.md"

cat > "$CSM_TEST_LAUNCH_SCRIPT" <<EOF
#!/bin/sh
set -eu
exec env \\
  HOME="$CSM_TEST_HOME" \\
  PATH="$CSM_TEST_PATH" \\
  CODEX_HOME="$CSM_TEST_CODEX_HOME" \\
  CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \\
EOF
if [ -n "$CSM_SOURCE_CODEX_BIN" ]; then
  printf '  CSM_CODEX_BIN="%s" \\\n' "$CSM_SOURCE_CODEX_BIN" >> "$CSM_TEST_LAUNCH_SCRIPT"
fi
cat >> "$CSM_TEST_LAUNCH_SCRIPT" <<EOF
  CSM_DATA_DIR="$CSM_TEST_ROOT/data" \\
  CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \\
  CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \\
  CSM_LOG_DIR="$CSM_TEST_ROOT/log" \\
  "$CSM_TEST_EXECUTABLE"
EOF
chmod 700 "$CSM_TEST_LAUNCH_SCRIPT"

if [ "$CSM_OPEN_TEST_APP" = "1" ]; then
  env HOME="$CSM_TEST_HOME" \
    PATH="$CSM_TEST_PATH" \
    CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \
    ${CSM_SOURCE_CODEX_BIN:+CSM_CODEX_BIN="$CSM_SOURCE_CODEX_BIN"} \
    CSM_DATA_DIR="$CSM_TEST_ROOT/data" \
    CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \
    CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" \
    CSM_LOG_DIR="$CSM_TEST_ROOT/log" \
    "$CSM_TEST_EXECUTABLE" >/dev/null 2>&1 &
fi

cat <<EOF

测试安装完成：
  TEST_ROOT=$CSM_TEST_ROOT
  HOME=$CSM_TEST_HOME
  CODEX_HOME=$CSM_TEST_CODEX_HOME
  APP=$CSM_TEST_APP
  EXECUTABLE=$CSM_TEST_EXECUTABLE
  LAUNCHER=$CSM_TEST_LAUNCHER
  SKILL=$CSM_TEST_SKILL
  LAUNCH_SCRIPT=$CSM_TEST_LAUNCH_SCRIPT

启动隔离 GUI（请直接执行 bundle 内二进制，不要用 open，以确保环境变量生效）：
  env HOME="$CSM_TEST_HOME" PATH="$CSM_TEST_PATH" \\
  CODEX_HOME="$CSM_TEST_CODEX_HOME" CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \\
  ${CSM_SOURCE_CODEX_BIN:+CSM_CODEX_BIN="$CSM_SOURCE_CODEX_BIN"} \\
  CSM_DATA_DIR="$CSM_TEST_ROOT/data" CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \\
  CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" CSM_LOG_DIR="$CSM_TEST_ROOT/log" \\
  "$CSM_TEST_EXECUTABLE"

也可以直接启动生成的脚本：
  "$CSM_TEST_LAUNCH_SCRIPT"

在同一测试环境运行 CLI：
  HOME="$CSM_TEST_HOME" PATH="$CSM_TEST_PATH" \\
  CODEX_HOME="$CSM_TEST_CODEX_HOME" CSM_CODEX_HOME="$CSM_TEST_CODEX_HOME" \\
  ${CSM_SOURCE_CODEX_BIN:+CSM_CODEX_BIN="$CSM_SOURCE_CODEX_BIN"} \\
  CSM_DATA_DIR="$CSM_TEST_ROOT/data" CSM_CONFIG_DIR="$CSM_TEST_ROOT/config" \\
  CSM_CACHE_DIR="$CSM_TEST_ROOT/cache" CSM_LOG_DIR="$CSM_TEST_ROOT/log" \\
  "$CSM_TEST_LAUNCHER" threads list

注意：测试目录包含当前 Codex home 的副本，可能含认证信息；测试结束后请只删除上面的 TEST_ROOT。
EOF
