#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
.tools/godot --headless --path godot --editor --import --quit > artifacts/godot-import.log 2>&1
if rg -n 'SCRIPT ERROR|ERROR:' artifacts/godot-import.log; then
  exit 1
fi
timeout 30 .tools/godot --headless --path godot --script res://tests/rig_check.gd > artifacts/rig-test.log 2>&1
if rg -n 'SCRIPT ERROR|ERROR:' artifacts/rig-test.log; then
  exit 1
fi
cat artifacts/rig-test.log
if [[ -f artifacts/3d/generated/creature.glb ]]; then
  timeout 30 .tools/godot --headless --path godot --script res://tests/volume_check.gd > artifacts/volume-test.log 2>&1
  if rg -n 'SCRIPT ERROR|ERROR:' artifacts/volume-test.log; then
    exit 1
  fi
  cat artifacts/volume-test.log
  timeout 30 .tools/godot --headless --path godot --script res://tests/room_3d_check.gd > artifacts/room-3d-test.log 2>&1
  if rg -n 'SCRIPT ERROR|ERROR:' artifacts/room-3d-test.log; then
    exit 1
  fi
  cat artifacts/room-3d-test.log
fi
