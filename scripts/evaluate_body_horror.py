"""Matched-seed runtime comparison: same guide, LCM, strength and prompt; only LoRA changes."""

import argparse
import json
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"


def run(args):
    import numpy as np
    from PIL import Image, ImageDraw

    from spookyneuro.config import Settings
    from spookyneuro.renderer import Renderer
    from spookyneuro.runtime import gpu_job
    from spookyneuro.temporal import BODY_PROMPT

    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    guide = Image.open(root / "artifacts/3d/guide.png").convert("RGBA")
    with gpu_job():
        renderer = Renderer(
            Settings(
                size=384,
                steps=4,
                strength=0.65,
                mask_mode="fixed",
                prompt=BODY_PROMPT,
                lora=str(Path(args.lora).resolve()),
            ),
            local_files_only=True,
        )
        sheet = Image.new("RGB", (768, 416 * 4), "#141414")
        draw = ImageDraw.Draw(sheet)
        rows = []
        for row, seed in enumerate([1928, 2718, 3141, 7281]):
            renderer.settings.seed = seed
            outputs = []
            for column, scale in enumerate([0.0, 0.55]):
                renderer.temporal_noise = None
                image, _stats = renderer.render(guide, {"phase": 0, "lora_scale": scale})
                image.save(output / f"{seed}-{scale:.2f}.png")
                sheet.paste(image.convert("RGB"), (column * 384, row * 416))
                draw.text(
                    (column * 384 + 8, row * 416 + 389), f"seed {seed} / LoRA {scale:.2f}", fill="white"
                )
                outputs.append(np.asarray(image)[..., :3].astype("float32"))
            rows.append(
                {"seed": seed, "rgb_mean_absolute_difference": float(np.abs(outputs[1] - outputs[0]).mean())}
            )
        sheet.save(output / "comparison.jpg")
        (output / "matched-seeds.json").write_text(
            json.dumps(
                {
                    "prompt": BODY_PROMPT,
                    "size": 384,
                    "steps": 4,
                    "strength": 0.65,
                    "lora_scale": 0.55,
                    "rows": rows,
                    "note": "Pixel difference verifies an effect, not artistic quality. Review comparison.jpg.",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lora", default="artifacts/body-horror-lora/lora")
    parser.add_argument("--output", default="artifacts/body-horror-lora/evaluation")
    run(parser.parse_args())
