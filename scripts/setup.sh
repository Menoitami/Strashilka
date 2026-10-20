#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tools
if [[ ! -x .tools/uv ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$PWD/.tools" UV_NO_MODIFY_PATH=1 sh
fi
.tools/uv python install 3.12
.tools/uv sync --frozen --extra dev --extra mask
if [[ ! -x .tools/godot ]]; then
  version=4.7.2
  curl -Lf --retry 2 "https://github.com/godotengine/godot/releases/download/${version}-stable/Godot_v${version}-stable_linux.x86_64.zip" -o .tools/godot.zip
  .venv/bin/python - <<'PY'
import pathlib
import zipfile
with zipfile.ZipFile('.tools/godot.zip') as archive:
    archive.extractall('.tools')
path = next(pathlib.Path('.tools').glob('Godot*linux.x86_64'))
path.chmod(0o755)
pathlib.Path('.tools/godot').symlink_to(path.name)
PY
fi
.tools/godot --headless --path godot --editor --import --quit
