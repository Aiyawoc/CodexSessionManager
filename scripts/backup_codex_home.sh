#!/bin/bash
set -Eeuo pipefail

# Create and verify a local-only, age-encrypted rollback snapshot of the
# non-credential data in a Codex home. This is separate from CSM's logical
# per-thread backup and is never a substitute for App Server fingerprints or
# immutable plan gates.

umask 077

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CSM_HOME=${HOME:?HOME must be set}
CSM_EXPECTED_AGE_VERSION="v1.3.1"
CSM_AGE_BIN=""
CSM_TEMP_TO_REMOVE=""
CSM_STAGE_TO_REMOVE=""

usage() {
  cat >&2 <<'EOF'
用法:
  scripts/backup_codex_home.sh create \
    --source /absolute/path/.codex \
    --destination /absolute/path/codex-home.tar.age \
    --recipients-file /absolute/path/recipients.txt

  scripts/backup_codex_home.sh verify \
    --backup /absolute/path/codex-home.tar.age \
    --identity-file /absolute/path/identity.txt

  scripts/backup_codex_home.sh restore \
    --backup /absolute/path/codex-home.tar.age \
    --identity-file /absolute/path/identity.txt \
    --target /absolute/path/new-codex-home \
    --confirm-restore "RESTORE CODEX HOME"

说明:
  - 仅支持 macOS；默认优先使用仓库 vendor/age/age，也可用 CSM_AGE_BIN 指定
    已通过 csm doctor 校验的 bundle 内 age。
  - create/restore 要求没有运行中的 codex 或 Codex desktop 进程。
  - destination 和 target 必须是不存在的路径；脚本不会合并、覆盖或删除既有目录。
  - 快照排除根目录 auth.json、credentials*.json、oauth 和 tokens；不会恢复登录态。
  - .codex 仍可能包含真实对话；快照只用于本机回滚，禁止打包、上传或共享。
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

cleanup() {
  if [ -n "$CSM_TEMP_TO_REMOVE" ] && [ -e "$CSM_TEMP_TO_REMOVE" ]; then
    rm -f "$CSM_TEMP_TO_REMOVE"
  fi
  if [ -n "$CSM_STAGE_TO_REMOVE" ] && [ -e "$CSM_STAGE_TO_REMOVE" ]; then
    rm -rf "$CSM_STAGE_TO_REMOVE"
  fi
}
trap cleanup EXIT INT TERM

require_tools() {
  if [ "$(uname -s)" != "Darwin" ]; then
    fail "this script requires macOS"
  fi
  local tool
  for tool in find tar shasum pgrep mktemp ln; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command not found: $tool"
  done
}

resolve_age() {
  local configured="${CSM_AGE_BIN:-}"
  if [ -n "$configured" ]; then
    if [ "${configured#/}" != "$configured" ]; then
      CSM_AGE_BIN="$configured"
    else
      CSM_AGE_BIN=$(command -v "$configured" || true)
    fi
  elif [ -x "$CSM_REPO_ROOT/vendor/age/age" ]; then
    CSM_AGE_BIN="$CSM_REPO_ROOT/vendor/age/age"
  else
    CSM_AGE_BIN=$(command -v age || true)
  fi
  [ -n "$CSM_AGE_BIN" ] || fail "age executable not found; set CSM_AGE_BIN"
  [ -x "$CSM_AGE_BIN" ] || fail "age executable is not runnable: $CSM_AGE_BIN"
  local version
  version=$("$CSM_AGE_BIN" --version 2>/dev/null || true)
  case "$version" in
    "$CSM_EXPECTED_AGE_VERSION" | 1.3.1) ;;
    *) fail "unsupported age version '$version'; expected $CSM_EXPECTED_AGE_VERSION" ;;
  esac
}

canonical_existing_dir() {
  local value=$1
  [ -d "$value" ] || fail "directory not found: $value"
  [ ! -L "$value" ] || fail "symbolic-link directory is not accepted: $value"
  CDPATH= cd -P -- "$value" && pwd -P
}

canonical_existing_file() {
  local value=$1
  [ -f "$value" ] || fail "regular file not found: $value"
  [ ! -L "$value" ] || fail "symbolic-link file is not accepted: $value"
  CDPATH= cd -P -- "$(dirname -- "$value")" &&
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "$value")"
}

canonical_output() {
  local value=$1
  case "$value" in
    /*) ;;
    *) fail "path must be absolute: $value" ;;
  esac
  local parent name
  parent=$(dirname -- "$value")
  [ -d "$parent" ] || fail "output parent directory must already exist: $parent"
  parent=$(CDPATH= cd -P -- "$parent" && pwd -P)
  name=$(basename -- "$value")
  [ "$name" != "." ] && [ "$name" != ".." ] || fail "invalid output name: $value"
  printf '%s/%s\n' "$parent" "$name"
}

reject_inside() {
  local candidate=$1
  local root=$2
  case "$candidate" in
    "$root" | "$root"/*) fail "path must not be the source or inside it: $candidate" ;;
  esac
}

reject_existing_output() {
  local value=$1
  if [ -e "$value" ] || [ -L "$value" ]; then
    fail "refusing to overwrite existing path: $value"
  fi
}

reject_running_codex() {
  local process_name exit_code
  for process_name in codex Codex; do
    if pgrep -x "$process_name" >/dev/null 2>&1; then
      fail "$process_name is running; quit Codex before snapshot/restore"
    else
      exit_code=$?
      [ "$exit_code" -eq 1 ] ||
        fail "unable to inspect running processes for $process_name"
    fi
  done
}

snapshot_entries() {
  find . -mindepth 1 \
    \( \
      -path './auth.json' -o \
      -path './credentials*.json' -o \
      -path './credentials.json.enc' -o \
      -path './oauth' -o \
      -path './tokens' \
    \) -prune -o \
    \( -type d -o -type f -o -type l \) -print0
}

publish_no_overwrite() {
  local temporary=$1
  local destination=$2
  reject_existing_output "$destination"
  ln -- "$temporary" "$destination" ||
    fail "cannot publish without overwriting: $destination"
  rm -f -- "$temporary"
}

validate_archive_members() {
  local backup=$1
  local identity=$2
  if ! (
    set -o pipefail
    "$CSM_AGE_BIN" --decrypt --identity "$identity" "$backup" |
      tar -tf - |
      while IFS= read -r member; do
        case "$member" in
          "" | /* | .. | ../* | */../* | */.. | ./../* | ./*/../*)
            exit 1
            ;;
        esac
      done
  ); then
    fail "encrypted snapshot is invalid, undecryptable, or contains an unsafe archive path"
  fi
}

verify_checksum() {
  local backup=$1
  local parent=$2
  local name=$3
  local sidecar="$backup.sha256"
  [ -f "$sidecar" ] || fail "checksum sidecar is missing: $sidecar"
  [ ! -L "$sidecar" ] || fail "checksum sidecar must not be a symbolic link: $sidecar"
  (
    CDPATH= cd -P -- "$parent"
    shasum -a 256 -c "$name.sha256" >/dev/null
  ) || fail "snapshot SHA-256 verification failed: $backup"
}

create_snapshot() {
  local source_arg=$1
  local destination_arg=$2
  local recipients_arg=$3
  local source
  source=$(canonical_existing_dir "$source_arg")
  local destination
  destination=$(canonical_output "$destination_arg")
  local destination_parent
  destination_parent=$(dirname -- "$destination")
  local destination_name
  destination_name=$(basename -- "$destination")
  local recipients
  recipients=$(canonical_existing_file "$recipients_arg")
  [ -s "$recipients" ] || fail "recipient file is empty: $recipients"
  reject_inside "$destination" "$source"
  reject_inside "$destination.sha256" "$source"
  reject_existing_output "$destination"
  reject_existing_output "$destination.sha256"
  reject_running_codex

  CSM_TEMP_TO_REMOVE=$(mktemp "$destination_parent/.$destination_name.XXXXXX")
  (
    CDPATH= cd -P -- "$source"
    snapshot_entries | tar -c --format pax --null --no-recursion -T - -f -
  ) |
    "$CSM_AGE_BIN" --encrypt --recipients-file "$recipients" \
      --output "$CSM_TEMP_TO_REMOVE"
  chmod 600 "$CSM_TEMP_TO_REMOVE"

  local digest
  digest=$(shasum -a 256 "$CSM_TEMP_TO_REMOVE" | awk '{print $1}')
  local checksum_temp
  checksum_temp=$(mktemp "$destination_parent/.$destination_name.sha256.XXXXXX")
  printf '%s  %s\n' "$digest" "$destination_name" > "$checksum_temp"
  chmod 600 "$checksum_temp"

  publish_no_overwrite "$CSM_TEMP_TO_REMOVE" "$destination"
  CSM_TEMP_TO_REMOVE=""
  publish_no_overwrite "$checksum_temp" "$destination.sha256"

  echo "snapshot=$destination"
  echo "sha256=$digest"
  echo "checksum=$destination.sha256"
}

verify_snapshot() {
  local backup_arg=$1
  local identity_arg=$2
  local backup
  backup=$(canonical_existing_file "$backup_arg")
  local identity
  identity=$(canonical_existing_file "$identity_arg")
  local parent
  parent=$(dirname -- "$backup")
  local name
  name=$(basename -- "$backup")
  verify_checksum "$backup" "$parent" "$name"
  validate_archive_members "$backup" "$identity"
  echo "verified=$backup"
  echo "sha256=$(shasum -a 256 "$backup" | awk '{print $1}')"
}

restore_snapshot() {
  local backup_arg=$1
  local identity_arg=$2
  local target_arg=$3
  local confirmation=$4
  [ "$confirmation" = "RESTORE CODEX HOME" ] ||
    fail "restore requires --confirm-restore 'RESTORE CODEX HOME'"
  case "$target_arg" in
    /*) ;;
    *) fail "restore target must be absolute: $target_arg" ;;
  esac
  case "$target_arg" in
    / | "$CSM_HOME") fail "refusing to use / or HOME as restore target" ;;
  esac
  reject_existing_output "$target_arg"
  local backup
  backup=$(canonical_existing_file "$backup_arg")
  local identity
  identity=$(canonical_existing_file "$identity_arg")
  local backup_parent
  backup_parent=$(dirname -- "$backup")
  local backup_name
  backup_name=$(basename -- "$backup")
  verify_checksum "$backup" "$backup_parent" "$backup_name"
  reject_running_codex
  validate_archive_members "$backup" "$identity"

  local target_parent
  target_parent=$(dirname -- "$target_arg")
  mkdir -p -m 700 -- "$target_parent"
  target_parent=$(CDPATH= cd -P -- "$target_parent" && pwd -P)
  local target_name
  target_name=$(basename -- "$target_arg")
  CSM_STAGE_TO_REMOVE=$(mktemp -d "$target_parent/.$target_name.restore.XXXXXX")
  chmod 700 "$CSM_STAGE_TO_REMOVE"
  "$CSM_AGE_BIN" --decrypt --identity "$identity" "$backup" |
    tar -xpf - -C "$CSM_STAGE_TO_REMOVE"
  chmod 700 "$CSM_STAGE_TO_REMOVE"
  reject_existing_output "$target_arg"
  mv -- "$CSM_STAGE_TO_REMOVE" "$target_arg"
  CSM_STAGE_TO_REMOVE=""
  echo "restored=$target_arg"
  echo "source_sha256=$(shasum -a 256 "$backup" | awk '{print $1}')"
}

require_option_value() {
  [ "$#" -ge 2 ] || fail "$1 requires a value"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

require_tools
resolve_age

CSM_COMMAND=${1:-}
[ -n "$CSM_COMMAND" ] || { usage; exit 2; }
shift

CSM_SOURCE=""
CSM_DESTINATION=""
CSM_RECIPIENTS=""
CSM_BACKUP=""
CSM_IDENTITY=""
CSM_TARGET=""
CSM_CONFIRM=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      require_option_value "$@"
      CSM_SOURCE=$2
      shift 2
      ;;
    --destination)
      require_option_value "$@"
      CSM_DESTINATION=$2
      shift 2
      ;;
    --recipients-file)
      require_option_value "$@"
      CSM_RECIPIENTS=$2
      shift 2
      ;;
    --backup)
      require_option_value "$@"
      CSM_BACKUP=$2
      shift 2
      ;;
    --identity-file)
      require_option_value "$@"
      CSM_IDENTITY=$2
      shift 2
      ;;
    --target)
      require_option_value "$@"
      CSM_TARGET=$2
      shift 2
      ;;
    --confirm-restore)
      require_option_value "$@"
      CSM_CONFIRM=$2
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage
      fail "unknown option: $1"
      ;;
  esac
done

case "$CSM_COMMAND" in
  create)
    [ -n "$CSM_SOURCE" ] || fail "create requires --source"
    [ -n "$CSM_DESTINATION" ] || fail "create requires --destination"
    [ -n "$CSM_RECIPIENTS" ] || fail "create requires --recipients-file"
    create_snapshot "$CSM_SOURCE" "$CSM_DESTINATION" "$CSM_RECIPIENTS"
    ;;
  verify)
    [ -n "$CSM_BACKUP" ] || fail "verify requires --backup"
    [ -n "$CSM_IDENTITY" ] || fail "verify requires --identity-file"
    verify_snapshot "$CSM_BACKUP" "$CSM_IDENTITY"
    ;;
  restore)
    [ -n "$CSM_BACKUP" ] || fail "restore requires --backup"
    [ -n "$CSM_IDENTITY" ] || fail "restore requires --identity-file"
    [ -n "$CSM_TARGET" ] || fail "restore requires --target"
    restore_snapshot "$CSM_BACKUP" "$CSM_IDENTITY" "$CSM_TARGET" "$CSM_CONFIRM"
    ;;
  *)
    usage
    fail "command must be create, verify, or restore"
    ;;
esac
