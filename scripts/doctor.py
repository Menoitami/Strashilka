"""Read-only installation diagnostics, including a real CUDA kernel and cache check."""

import platform
import sys
from importlib import import_module
from pathlib import Path

import torch
from download_models import download

from spookyneuro.runtime import godot_command

root = Path(__file__).resolve().parents[1]
print("Platform:", platform.system(), platform.machine(), "Python:", platform.python_version())
print("PyTorch:", torch.__version__, "CUDA runtime:", torch.version.cuda)
if not torch.cuda.is_available():
    sys.exit("CUDA is unavailable. Check nvidia-smi and the NVIDIA driver. This build needs NVIDIA CUDA.")
print("GPU:", torch.cuda.get_device_name(0))
print("VRAM GiB:", round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1))
for dependency in ("rembg", "xatlas", "omegaconf", "einops", "skimage", "numba", "psutil"):
    import_module(dependency)
try:
    value = (torch.ones((32, 32), device="cuda") @ torch.ones((32, 32), device="cuda")).sum().item()
    assert value == 32768
except (RuntimeError, AssertionError) as error:
    sys.exit("CUDA kernel failed: " + str(error))
if not Path(godot_command(root)[0]).is_file():
    sys.exit("Missing Godot executable")
for filename in [
    ".tools/TripoSR/tsr/system.py",
    "artifacts/3d/generated/creature.glb",
    "artifacts/3d/generated/unrigged.ply",
    "artifacts/3d/guide.png",
    "artifacts/body-horror-lora/lora/pytorch_lora_weights.safetensors",
    "assets/creature/realism-reference.png",
    "assets/creature/realistic/creature.glb",
    "assets/creature/realistic/unrigged.ply",
    "assets/creature/realistic/guide.png",
    "assets/creature/realistic/rig.json",
    "assets/creature/realistic/profile.json",
]:
    if not (root / filename).is_file():
        sys.exit("Missing: " + filename)
download(offline=True)
print("Installation check passed.")
