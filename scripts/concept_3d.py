"""Generate a rig-friendly A-pose using the project's real diffusion model."""

from pathlib import Path

from PIL import Image

from spookyneuro.config import Settings
from spookyneuro.renderer import Renderer
from spookyneuro.runtime import gpu_job

root = Path(__file__).resolve().parents[1]
output = root / "artifacts/3d"
source = Image.open(output / "guide.png")
settings = Settings(
    size=512,
    steps=4,
    strength=0.9,
    mask_mode="fixed",
    seed=147,
    prompt="full body photograph of a terrifying emaciated humanoid creature, pale diseased leathery skin, "
    "skeletal torso, long thin arms, deformed human face, dark hollow eye sockets, "
    "standing in symmetrical A pose, arms apart from body, legs apart, practical horror movie monster, "
    "detailed skin texture, single creature, studio lighting, plain background",
)
lora = root / "artifacts/horror-lora/lora"
if lora.exists():
    settings.lora = str(lora)
with gpu_job(True):
    renderer = Renderer(settings)
    for index in range(2):
        result, meta = renderer.render(source, {"phase": float(index) * 3})
        result.save(output / f"concept_{index}.png")
        print(meta, flush=True)
