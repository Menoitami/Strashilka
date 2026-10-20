import csv
import json
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from .imaging import flow_fields, interpolate, png_bytes, proxy_image
from .renderer import Renderer


def benchmark(settings, output, frames=12, mock=False, matrix=False, source=None):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(settings, mock=mock)
    combinations = (
        [(n, steps) for n in (256, 384, 512) for steps in (2, 4)]
        if matrix
        else [(settings.size, settings.steps)]
    )
    report = []
    for size, steps in combinations:
        renderer.settings = replace(settings, size=size, steps=steps).validate()
        run = out / f"{size}px_{steps}steps_{settings.mask_mode}_{settings.interpolation}"
        run.mkdir(exist_ok=True)
        image = Image.open(source).convert("RGBA") if source else proxy_image(size)
        renderer.render(image, {"phase": 0})  # warm-up excluded
        previous = None
        rows, animation = [], []
        for index in range(frames):
            started = time.perf_counter()
            current, metrics = renderer.render(image, {"phase": index * 0.25})
            current.save(run / f"key_{index:04d}.png")
            flow_start = time.perf_counter()
            fields = (
                flow_fields(previous, current)
                if previous is not None and settings.interpolation == "flow"
                else None
            )
            metrics["flow_ms"] = (time.perf_counter() - flow_start) * 1000
            interp_start = time.perf_counter()
            if previous is not None:
                for t in np.linspace(0, 1, 8, endpoint=False):
                    animation.append(interpolate(previous, current, t, fields).convert("RGB"))
            metrics["interpolation_8_frames_ms"] = (time.perf_counter() - interp_start) * 1000
            transfer_start = time.perf_counter()
            payload = png_bytes(current)
            metrics["png_encode_ms"] = (time.perf_counter() - transfer_start) * 1000
            metrics["bytes"] = len(payload)
            metrics["total_ms"] = (time.perf_counter() - started) * 1000
            metrics["frame"] = index
            rows.append(metrics)
            previous = current
        if animation:
            animation[0].save(
                run / "sequence.gif", save_all=True, append_images=animation[1:], duration=40, loop=0
            )
        if animation and shutil.which("ffmpeg"):
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(run / "sequence.gif"),
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-pix_fmt",
                    "yuv420p",
                    str(run / "sequence.mp4"),
                ],
                check=True,
            )
        with (run / "frames.csv").open("w") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        render_times = [r["render_ms"] + r["flow_ms"] + r["png_encode_ms"] for r in rows]
        item = {
            "size": size,
            "steps": steps,
            "actual_steps": rows[0]["actual_steps"],
            "median_service_ms": float(np.median(render_times)),
            "p95_service_ms": float(np.percentile(render_times, 95)),
            "updates_per_second": 1000 / float(np.median(render_times)),
            "peak_vram_mib": max(r["peak_vram_mib"] for r in rows),
            "device_used_mib": max(r["device_used_mib"] for r in rows),
            "mask_provider": rows[-1]["mask_provider"],
            "segmentation_median_ms": float(np.median([r["segmentation_ms"] for r in rows])),
            "mock": mock,
        }
        report.append(item)
        print(json.dumps(item), flush=True)
    (out / "report.json").write_text(json.dumps({"settings": settings.to_dict(), "runs": report}, indent=2))
