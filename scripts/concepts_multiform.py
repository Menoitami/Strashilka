"""Generate visibly distinct diffusion appearances under a shared humanoid pose."""

import argparse
import json
from pathlib import Path

from PIL import Image

from spookyneuro.config import Settings
from spookyneuro.renderer import Renderer
from spookyneuro.runtime import gpu_job

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--seed", type=int, default=1927)
parser.add_argument("--variant", choices=["swollen", "chitin"])
args = parser.parse_args()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
styles = {
    "swollen": "a swollen red fleshy humanoid monster, enormous bloated torso, bulbous misshapen head, thick arms, exposed red muscles, wet veiny crimson skin, tumors and folds, practical creature effects",
    "chitin": "a gaunt insectoid humanoid monster, narrow elongated skull, very thin waist, black armored beetle exoskeleton, glossy dark teal chitin plates, turquoise veins, sharp bone ridges, alien creature",
}
with gpu_job():
    settings = Settings(size=512, steps=4, strength=0.95, mask_mode="fixed", seed=args.seed)
    lora = Path("artifacts/horror-lora/lora")
    if lora.exists():
        settings.lora = str(lora)
        settings.lora_scale = 0.35
    renderer = Renderer(settings)
    for index, (name, prompt) in enumerate(styles.items()):
        if args.variant and name != args.variant:
            continue
        renderer.settings.prompt = (
            prompt
            + ", full body front view, standing A pose, hands away from hips, feet apart, single creature, isolated plain background, detailed surface texture"
        )
        result, stats = renderer.render(Image.open(f"artifacts/3d/guide_{name}.png"), {"phase": index * 3.0})
        result.save(output / f"{name}.png")
        (output / f"{name}.json").write_text(
            json.dumps(dict(stats, prompt=renderer.settings.prompt, seed=args.seed), indent=2)
        )
        print(name, stats, flush=True)
