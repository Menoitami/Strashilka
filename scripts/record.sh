#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
record_dir="$PWD/artifacts/recording-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$record_dir"
.venv/bin/spooky serve --log artifacts/recording-server.jsonl "$@" > artifacts/recording-server.log 2>&1 &
renderer_pid=$!
trap 'kill "$renderer_pid" 2>/dev/null || true; wait "$renderer_pid" 2>/dev/null || true' EXIT INT TERM
.tools/godot --path godot --disable-vsync --max-fps 60 res://main.tscn -- --smoke-seconds=60 --smoke-output="$PWD/artifacts/recording" --record-dir="$record_dir" > artifacts/recording-game.log 2>&1
ffmpeg -v error -y -framerate 10 -i "$record_dir/frame_%05d.png" -pix_fmt yuv420p artifacts/recording.mp4
