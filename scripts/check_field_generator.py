"""Small real-model ablation used to verify temporal image conditioning."""
import argparse
from pathlib import Path

from PIL import Image

from spookyneuro.config import Settings
from spookyneuro.neural_field import PROMPTS, feedback_image
from spookyneuro.renderer import Renderer
from spookyneuro.runtime import gpu_job


def run(output):
    import torch
    output.mkdir(parents=True, exist_ok=True)
    anchor = Image.open("assets/creature/realistic/guide.png")
    with gpu_job():
        renderer = Renderer(Settings(size=384, steps=6, strength=.68, mask_mode="free",
                                     mask_device="cpu", prompt=PROMPTS[0], seed=1928), local_files_only=True)
        for mode in ("constant", "feedback", "embeddings"):
            previous = None
            for i in range(4):
                if mode == "embeddings":
                    with torch.inference_mode():
                        renderer.embeddings[PROMPTS[0]] = renderer.pipe.encode_prompt(PROMPTS[0],"cuda",1,False)[0]
                image, _ = renderer.render(feedback_image(anchor,previous,.35) if mode != "constant" else anchor,
                                           {"phase":i*.3,"coherence":0,"guidance_scale":2.0})
                image.save(output / f"{mode}_{i}.png")
                previous = image


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("artifacts/field-ablation"))
    run(parser.parse_args().output)
