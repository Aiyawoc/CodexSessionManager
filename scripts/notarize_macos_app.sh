#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 APP_PATH NOTARYTOOL_PROFILE" >&2
  exit 2
fi
CSM_APP=$1
CSM_PROFILE=$2
test -d "$CSM_APP"
CSM_ZIP=$(mktemp "${TMPDIR:-/tmp}/CodexSessionManager.XXXXXX.zip")
trap 'rm -f "$CSM_ZIP"' EXIT INT TERM
ditto -c -k --keepParent "$CSM_APP" "$CSM_ZIP"
xcrun notarytool submit "$CSM_ZIP" --keychain-profile "$CSM_PROFILE" --wait
xcrun stapler staple "$CSM_APP"
spctl --assess --type execute --verbose=4 "$CSM_APP"

