#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CSM_ICONSET="$CSM_REPO_ROOT/build/CodexSessionManager.iconset"
CSM_PNG="$CSM_REPO_ROOT/build/CodexSessionManager-1024.png"
CSM_ICNS="$CSM_REPO_ROOT/build/CodexSessionManager.icns"
if [ -f "$CSM_ICNS" ] && [ "$CSM_ICNS" -nt "$CSM_REPO_ROOT/assets/app-icon.svg" ]; then
  exit 0
fi
mkdir -p "$CSM_ICONSET"

if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 1024 -h 1024 "$CSM_REPO_ROOT/assets/app-icon.svg" -o "$CSM_PNG"
else
  qlmanage -t -s 1024 -o "$CSM_REPO_ROOT/build" "$CSM_REPO_ROOT/assets/app-icon.svg" >/dev/null
  mv "$CSM_REPO_ROOT/build/app-icon.svg.png" "$CSM_PNG"
fi

for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$CSM_PNG" --out "$CSM_ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$CSM_PNG" --out "$CSM_ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$CSM_ICONSET" -o "$CSM_ICNS"
