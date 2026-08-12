#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/CodexSessionManager.app" >&2
  exit 2
fi

CSM_SOURCE_APP=$1
CSM_INSTALL_ROOT="$HOME/Applications"
CSM_FINAL_APP="$CSM_INSTALL_ROOT/CodexSessionManager.app"
CSM_PREVIOUS_APP="$CSM_INSTALL_ROOT/CodexSessionManager.previous.app"
CSM_STAGING_APP="$CSM_INSTALL_ROOT/.CodexSessionManager.$$.new.app"
CSM_FINAL_LAUNCHER="$HOME/.local/bin/csm"
CSM_STAGING_LAUNCHER="$HOME/.local/bin/.csm.$$.new"
CSM_PREVIOUS_LAUNCHER="$HOME/.local/bin/.csm.$$.previous"
CSM_SKILL_LINK="$HOME/.agents/skills/manage-codex-sessions"
CSM_SKILL_TARGET="$CSM_FINAL_APP/Contents/Resources/skills/manage-codex-sessions"
CSM_SWAPPED=0
CSM_LAUNCHER_BACKED_UP=0
CSM_LAUNCHER_INSTALLED=0
CSM_SKILL_LINK_INSTALLED=0
# Isolated bundle tests can skip the external Codex App Server probe.
CSM_INSTALL_SKIP_APP_SERVER=${CSM_INSTALL_SKIP_APP_SERVER:-0}
test -d "$CSM_SOURCE_APP"
test -f "$CSM_SOURCE_APP/Contents/Resources/skills/manage-codex-sessions/SKILL.md"
if [ -e "$CSM_SKILL_LINK" ] || [ -L "$CSM_SKILL_LINK" ]; then
  if [ ! -L "$CSM_SKILL_LINK" ] || [ "$(readlink "$CSM_SKILL_LINK")" != "$CSM_SKILL_TARGET" ]; then
    echo "refusing to replace an existing skill: $CSM_SKILL_LINK" >&2
    exit 1
  fi
fi
mkdir -p "$CSM_INSTALL_ROOT" "$HOME/.local/bin" "$HOME/.agents/skills" "$HOME/.Trash"

run_doctor() {
  CSM_DOCTOR_TARGET=$1
  if [ "$CSM_INSTALL_SKIP_APP_SERVER" = "1" ]; then
    "$CSM_DOCTOR_TARGET" doctor --skip-app-server
  else
    "$CSM_DOCTOR_TARGET" doctor
  fi
}

rollback_install() {
  if [ "$CSM_SKILL_LINK_INSTALLED" -eq 1 ] && [ -L "$CSM_SKILL_LINK" ]; then
    rm "$CSM_SKILL_LINK"
  fi
  if [ -d "$CSM_STAGING_APP" ]; then
    mv "$CSM_STAGING_APP" "$HOME/.Trash/CSM-failed-install-$$.app"
  fi
  if [ "$CSM_SWAPPED" -eq 1 ]; then
    if [ -d "$CSM_FINAL_APP" ]; then
      mv "$CSM_FINAL_APP" "$HOME/.Trash/CSM-failed-postcheck-$$.app"
    fi
    if [ -d "$CSM_PREVIOUS_APP" ]; then
      mv "$CSM_PREVIOUS_APP" "$CSM_FINAL_APP"
    fi
  fi
  if [ -f "$CSM_STAGING_LAUNCHER" ]; then
    mv "$CSM_STAGING_LAUNCHER" "$HOME/.Trash/CSM-failed-launcher-stage-$$"
  fi
  if [ "$CSM_LAUNCHER_INSTALLED" -eq 1 ]; then
    if [ -f "$CSM_FINAL_LAUNCHER" ]; then
      mv "$CSM_FINAL_LAUNCHER" "$HOME/.Trash/CSM-failed-launcher-$$"
    fi
  fi
  if [ "$CSM_LAUNCHER_BACKED_UP" -eq 1 ]; then
    if [ -f "$CSM_PREVIOUS_LAUNCHER" ]; then
      mv "$CSM_PREVIOUS_LAUNCHER" "$CSM_FINAL_LAUNCHER"
    fi
  fi
}
trap rollback_install EXIT INT TERM

ditto "$CSM_SOURCE_APP" "$CSM_STAGING_APP"
codesign --verify --deep --strict "$CSM_STAGING_APP"
if [ "$CSM_INSTALL_SKIP_APP_SERVER" = "1" ]; then
  "$CSM_STAGING_APP/Contents/MacOS/CodexSessionManager" cli doctor --skip-app-server
else
  "$CSM_STAGING_APP/Contents/MacOS/CodexSessionManager" cli doctor
fi

if [ -d "$CSM_PREVIOUS_APP" ]; then
  mv "$CSM_PREVIOUS_APP" "$HOME/.Trash/CodexSessionManager.previous.$(date +%Y%m%dT%H%M%S).app"
fi
if [ -d "$CSM_FINAL_APP" ]; then
  mv "$CSM_FINAL_APP" "$CSM_PREVIOUS_APP"
fi
mv "$CSM_STAGING_APP" "$CSM_FINAL_APP"
CSM_SWAPPED=1
install -m 0755 "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/packaging/csm-launcher" "$CSM_STAGING_LAUNCHER"
if [ -f "$CSM_FINAL_LAUNCHER" ]; then
  mv "$CSM_FINAL_LAUNCHER" "$CSM_PREVIOUS_LAUNCHER"
  CSM_LAUNCHER_BACKED_UP=1
fi
mv "$CSM_STAGING_LAUNCHER" "$CSM_FINAL_LAUNCHER"
CSM_LAUNCHER_INSTALLED=1
run_doctor "$CSM_FINAL_LAUNCHER"
test -f "$CSM_SKILL_TARGET/SKILL.md"
if [ ! -L "$CSM_SKILL_LINK" ]; then
  ln -s "$CSM_SKILL_TARGET" "$CSM_SKILL_LINK"
  CSM_SKILL_LINK_INSTALLED=1
fi
if [ -f "$CSM_PREVIOUS_LAUNCHER" ]; then
  mv "$CSM_PREVIOUS_LAUNCHER" "$HOME/.Trash/CSM-previous-launcher-$$"
fi
CSM_LAUNCHER_BACKED_UP=0
CSM_LAUNCHER_INSTALLED=0
CSM_SKILL_LINK_INSTALLED=0
CSM_SWAPPED=0
trap - EXIT INT TERM
