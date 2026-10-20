#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
.venv/bin/spooky serve --log artifacts/soak-server.jsonl "$@" > artifacts/soak-server.log 2>&1 &
renderer_pid=$!
trap 'kill "$renderer_pid" 2>/dev/null || true; wait "$renderer_pid" 2>/dev/null || true' EXIT INT TERM
.tools/godot --path godot --disable-vsync --max-fps 60 res://main.tscn -- --smoke-seconds=600 --scenario --smoke-output="$PWD/artifacts/soak" > artifacts/soak-game.log 2>&1
