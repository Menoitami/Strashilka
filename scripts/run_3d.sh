#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
generate=false
source_path=""
custom_source=false
scene_path=res://room_3d.tscn
while [[ $# -gt 0 ]]; do
  case "$1" in
    --generate) generate=true; shift ;;
    --source) source_path="$(realpath "$2")"; custom_source=true; generate=true; shift 2 ;;
    --viewer) scene_path=res://volume_lab.tscn; shift ;;
    *) break ;;
  esac
done
if [[ ! -x .tools/godot || ! -x .venv/bin/spooky ]]; then scripts/setup_3d.sh; fi
if [[ "$generate" == true && "$custom_source" == false && "$scene_path" == res://room_3d.tscn && -f assets/creature/realism-reference.png ]]; then
  if ! .venv/bin/python -c 'import omegaconf, einops, skimage, trimesh, imageio' || [[ ! -f .tools/TripoSR/tsr/system.py ]]; then
    scripts/setup_3d.sh
  fi
  .venv/bin/python scripts/build_realistic_base.py
  generate=false
fi
if [[ "$generate" == true || -n "$source_path" || ! -f artifacts/3d/generated/creature.glb ]]; then
  if ! .venv/bin/python -c 'import omegaconf, einops, skimage, trimesh, imageio' || [[ ! -f .tools/TripoSR/tsr/system.py ]]; then
    scripts/setup_3d.sh
  fi
  mkdir -p artifacts/3d
  if [[ -z "$source_path" ]]; then
    .tools/godot --path godot --script res://tools/export_concept.gd
    .venv/bin/python scripts/concept_3d.py
    source_path=artifacts/3d/concept_0.png
  fi
  .venv/bin/spooky generate-3d --source "$source_path"
  mkdir -p unity/Assets/SpookyNeuro/Models
  cp artifacts/3d/generated/creature.spooky.json unity/Assets/SpookyNeuro/Models/
fi
if [[ "$custom_source" == true ]]; then
  exec .tools/godot --path godot --disable-vsync --max-fps 60 "$scene_path" -- --offline --model=res://../artifacts/3d/generated/creature.glb "$@"
fi
if [[ "$scene_path" == res://room_3d.tscn ]]; then
  if ! .venv/bin/python -c 'import xatlas, omegaconf, skimage, numba'; then scripts/setup_3d.sh; fi
  for variant in base swollen; do
    guide=artifacts/3d/guide.png
    if [[ "$variant" != base ]]; then guide="artifacts/3d/guide_${variant}.png"; fi
    if [[ ! -f "$guide" ]]; then
      .tools/godot --path godot --script res://tools/export_concept.gd -- "--variant=$variant"
    fi
  done
fi
# The normal room opens only after real neural inference has produced a packet.
# Offline/static diagnostic modes intentionally work without a neural worker.
wait_for_neural=true
for arg in "$@"; do
  case "$arg" in
    --offline|--model=*) wait_for_neural=false ;;
  esac
done
if [[ "$scene_path" == res://room_3d.tscn && "$wait_for_neural" == true ]]; then
  exec .venv/bin/python scripts/launch_3d.py "$@"
fi
exec .tools/godot --path godot --disable-vsync --max-fps 60 "$scene_path" -- "$@"
