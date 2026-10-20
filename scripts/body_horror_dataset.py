"""Reproducible synthetic anatomy study; teacher SD1.5, NOT collected real photographs."""

import argparse
import json
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"


def run(args):
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionImg2ImgPipeline
    from PIL import Image, ImageDraw

    from spookyneuro.runtime import gpu_job

    root = Path(__file__).resolve().parents[1]
    out = root / "data/body-horror"
    out.mkdir(parents=True, exist_ok=True)
    anatomy = [
        "asymmetrical swollen shoulder and twisted muscular torso, stretched skin",
        "sunken ribcage beneath stretched skin, long sinewy arms",
        "misshapen elongated skull, contracted jaw, knotted neck tendons",
        "human anatomy with bony growths along shoulders and spine, muscular legs",
        "fused skin folds across chest, displaced ribs, deformed human face",
        "hypertrophied forearms, crooked fingers, taut tendons and scars",
        "uneven muscular shoulders, sunken abdomen, vertebrae under skin",
        "contorted human proportions, swollen neck, sinews under stretched skin",
    ]
    palette = ["pale mottled skin", "ashen bruised skin", "waxy grey skin", "desaturated flesh"]
    records = []
    with gpu_job():
        pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
            "stable-diffusion-v1-5/stable-diffusion-v1-5",
            torch_dtype=torch.float16,
            local_files_only=True,
            safety_checker=None,
            requires_safety_checker=False,
        ).to("cuda")
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=True)
        for i in range(args.count):
            seed = 81000 + i
            split = "validation" if i % 8 == 7 else "train"
            filename = f"{split}/{seed}.png"
            path = out / filename
            path.parent.mkdir(exist_ok=True)
            prompt = (
                "anatomyhorror, full body humanoid body horror creature, "
                + anatomy[i % 8]
                + ", "
                + palette[(i // 8) % 4]
                + ", adult humanoid anatomy, two arms and two legs, "
                "standing A pose, hands away from hips, feet apart, single creature, "
                "practical prosthetic movie monster, realistic skin, black background"
            )
            if not path.exists():
                guide = (
                    Image.open(root / f"artifacts/3d/{'guide_swollen' if i % 3 == 0 else 'guide'}.png")
                    .convert("RGBA")
                    .resize((512, 512))
                )
                image = Image.new("RGB", guide.size, (8, 8, 8))
                image.paste(guide, mask=guide.getchannel("A"))
                with torch.inference_mode():
                    result = pipe(
                        prompt=prompt,
                        image=image,
                        strength=0.78,
                        guidance_scale=6.5,
                        negative_prompt="skeleton, anatomical chart, medical diagram, baby, child, abstract, statue, robot, armor, cartoon, toy, multiple bodies, text, cropped, landscape",
                        num_inference_steps=28,
                        generator=torch.Generator("cuda").manual_seed(seed),
                    ).images[0]
                result.save(path)
            records.append(
                {
                    "prepared_file": filename,
                    "split": split,
                    "class": "monster",
                    "caption": prompt,
                    "source": "synthetic SD1.5 img2img; local authored anatomical guide",
                    "seed": seed,
                    "teacher": "stable-diffusion-v1-5/stable-diffusion-v1-5",
                    "steps": 28,
                    "strength": 0.78,
                }
            )
            print(f"{i + 1}/{args.count} {filename}", flush=True)
    (out / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    for offset in range(0, len(records), 16):
        sheet = Image.new("RGB", (1024, 1080), "#222222")
        draw = ImageDraw.Draw(sheet)
        for k, record in enumerate(records[offset : offset + 16]):
            x, y = (k % 4) * 256, (k // 4) * 270
            sheet.paste(Image.open(out / record["prepared_file"]).resize((256, 256)), (x, y))
            draw.text((x + 5, y + 256), str(record["seed"]) + " " + record["split"], fill="white")
        sheet.save(out / f"contact-{offset // 16}.jpg")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=64)
    run(p.parse_args())
