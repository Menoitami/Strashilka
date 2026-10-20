#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# == 0 || "${1:-}" == "--3d" ]]; then
  if [[ "${1:-}" == "--3d" ]]; then shift; fi
  exec scripts/run_3d.sh "$@"
fi
if [[ "${1:-}" == "--2d" ]]; then shift; fi
if [[ ! -x .venv/bin/spooky || ! -x .tools/godot ]]; then
  scripts/setup.sh
fi
mkdir -p artifacts
# Prefer the locally trained adapter unless an explicit adapter was requested.
renderer_args=("$@")
explicit_lora=false
for arg in "$@"; do
  if [[ "$arg" == "--lora" || "$arg" == --lora=* ]]; then explicit_lora=true; fi
done
if [[ "$explicit_lora" == false && -f artifacts/horror-lora/lora/pytorch_lora_weights.safetensors ]]; then
  renderer_args+=(--lora artifacts/horror-lora/lora)
fi
.venv/bin/spooky serve "${renderer_args[@]}" > artifacts/renderer.log 2>&1 &
renderer_pid=$!
game_pid=""
cleanup() {
  kill "$renderer_pid" 2>/dev/null || true
  if [[ -n "$game_pid" ]]; then kill "$game_pid" 2>/dev/null || true; fi
  wait "$renderer_pid" 2>/dev/null || true
  if [[ -n "$game_pid" ]]; then wait "$game_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
.tools/godot --path godot res://main.tscn &
game_pid=$!
status=0
wait -n "$renderer_pid" "$game_pid" || status=$?
if ! kill -0 "$renderer_pid" 2>/dev/null; then
  cat artifacts/renderer.log >&2
  if [[ "$status" == 0 ]]; then status=1; fi
fi
exit "$status"
