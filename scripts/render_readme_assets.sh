#!/bin/sh
set -eu

CSM_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CSM_OUTPUT_ROOT=${1:-"$CSM_REPO_ROOT/docs/images"}
CSM_UV_CACHE_DIR=${UV_CACHE_DIR:-"$CSM_REPO_ROOT/build/.uv-cache"}
CSM_FFMPEG_BIN=${CSM_FFMPEG_BIN:-$(command -v ffmpeg || true)}
CSM_FRAME_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/csm-readme-frames.XXXXXX")

cleanup() {
  rm -rf "$CSM_FRAME_ROOT"
}
trap cleanup EXIT INT TERM

if [ -z "$CSM_FFMPEG_BIN" ]; then
  echo "error: ffmpeg is required to render the README GIFs" >&2
  exit 1
fi

mkdir -p "$CSM_OUTPUT_ROOT"

render_frame() {
  CSM_FRAME_LANGUAGE=$1
  CSM_FRAME_SCENE=$2
  CSM_FRAME_OUTPUT=$3
  QT_QPA_PLATFORM=offscreen UV_CACHE_DIR="$CSM_UV_CACHE_DIR" \
    uv run --locked python "$CSM_REPO_ROOT/scripts/render_gui_preview.py" \
    --language "$CSM_FRAME_LANGUAGE" --scene "$CSM_FRAME_SCENE" \
    --output "$CSM_FRAME_OUTPUT"
}

render_gif() {
  CSM_GIF_LANGUAGE=$1
  CSM_GIF_OUTPUT=$2
  CSM_LANGUAGE_FRAMES="$CSM_FRAME_ROOT/$CSM_GIF_LANGUAGE"
  mkdir -p "$CSM_LANGUAGE_FRAMES"
  CSM_FRAME_NUMBER=1
  for CSM_SCENE in overview inspect summary exclude markdown saved; do
    render_frame "$CSM_GIF_LANGUAGE" "$CSM_SCENE" \
      "$CSM_LANGUAGE_FRAMES/$(printf '%02d' "$CSM_FRAME_NUMBER").png"
    CSM_FRAME_NUMBER=$((CSM_FRAME_NUMBER + 1))
  done
  "$CSM_FFMPEG_BIN" -hide_banner -loglevel error -y \
    -framerate 1/2 -i "$CSM_LANGUAGE_FRAMES/%02d.png" \
    -vf "fps=8,scale=1200:675:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle" \
    -loop 0 "$CSM_GIF_OUTPUT"
  CSM_GIF_SIZE=$(wc -c < "$CSM_GIF_OUTPUT" | tr -d ' ')
  if [ "$CSM_GIF_SIZE" -gt 5242880 ]; then
    echo "error: GIF exceeds 5 MiB: $CSM_GIF_OUTPUT ($CSM_GIF_SIZE bytes)" >&2
    exit 1
  fi
}

render_frame zh overview "$CSM_OUTPUT_ROOT/gui-overview-cn.png"
render_frame en overview "$CSM_OUTPUT_ROOT/gui-overview-en.png"
render_gif zh "$CSM_OUTPUT_ROOT/context-trimming-demo-cn.gif"
render_gif en "$CSM_OUTPUT_ROOT/context-trimming-demo-en.gif"

echo "README assets rendered in $CSM_OUTPUT_ROOT"
