"""Compare interpolation on identical cached neural keyframes (no GPU/model needed)."""

import argparse
import itertools
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from spookyneuro.imaging import flow_fields, interpolate

parser = argparse.ArgumentParser()
parser.add_argument("--source", default="artifacts/comparison/after-gpu/256px_4steps_free_flow")
parser.add_argument("--output", default="artifacts/comparison/interpolation")
args = parser.parse_args()
paths = sorted(Path(args.source).glob("key_*.png"))
if len(paths) < 2:
    parser.error("Need at least two RGBA keyframes")
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
frames = []
for a_path, b_path in itertools.pairwise(paths):
    a, b = Image.open(a_path).convert("RGBA"), Image.open(b_path).convert("RGBA")
    fields = flow_fields(a, b)
    for t in np.linspace(0, 1, 8, endpoint=False):
        flow = interpolate(a, b, t, fields)
        blend = interpolate(a, b, t)
        canvas = Image.new("RGB", (a.width * 2, a.height + 24), (20, 28, 30))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 6), "Optical flow", fill=(210, 230, 220))
        draw.text((a.width + 8, 6), "Crossfade", fill=(210, 230, 220))
        canvas.paste(flow, (0, 24), flow.getchannel("A"))
        canvas.paste(blend, (a.width, 24), blend.getchannel("A"))
        frames.append(canvas)
frames[0].save(out / "comparison.gif", save_all=True, append_images=frames[1:], duration=40, loop=0)
if shutil.which("ffmpeg"):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(out / "comparison.gif"),
            "-pix_fmt",
            "yuv420p",
            str(out / "comparison.mp4"),
        ],
        check=True,
    )
print(out / "comparison.mp4")
