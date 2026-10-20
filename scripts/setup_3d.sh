#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .tools/uv || ! -x .tools/godot ]]; then
  scripts/setup.sh
fi
.tools/uv sync --frozen --extra dev --extra mask --extra mesh
revision=107cefdc244c39106fa830359024f6a2f1c78871
if [[ ! -f .tools/TripoSR/tsr/system.py ]]; then
  git clone https://github.com/VAST-AI-Research/TripoSR.git .tools/TripoSR
  git -C .tools/TripoSR checkout "$revision"
fi
# Cache diffusion + LCM as well as TripoSR: the live worker is deliberately offline.
.venv/bin/python scripts/download_models.py
.venv/bin/python scripts/doctor.py
printf '%s\n' 'Готово. Запуск: scripts/run_3d.sh'
