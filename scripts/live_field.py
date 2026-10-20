"""Continuous neural volume generation, independent of the player's camera."""

import argparse
import json
import os
import signal
import time
from pathlib import Path

import numpy as np
from live_3d import atomic_json
from PIL import Image


def run(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch

    from spookyneuro.config import Settings
    from spookyneuro.neural_field import (
        PROMPTS,
        change_focus,
        compare_direct,
        field_alignment,
        front_projection,
        image_continuity,
        sample_field,
        valid_silhouette,
        write_packet,
    )
    from spookyneuro.reconstruction import load_triposr, prepare_image
    from spookyneuro.renderer import Renderer
    from spookyneuro.runtime import gpu_job, process_exists

    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stopped = False
    start = time.monotonic()
    last_status = None

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def stopping():
        return stopped or (output / "stop").exists() or (args.parent and not process_exists(args.parent))

    def status(stage, **kwargs):
        nonlocal last_status
        if last_status == (stage, kwargs):
            return
        atomic_json(output / "status.json", {"stage": stage, "elapsed": time.monotonic()-start, **kwargs})
        last_status = (stage, kwargs)

    try:
        with gpu_job():
            status("Загрузка генератора образов")
            renderer = Renderer(Settings(size=512, steps=24, strength=.68, mask_mode="free",
                                         mask_device="cpu", seed=args.seed), local_files_only=True, quality=True)
            status("Загрузка нейронного объёма")
            model = load_triposr(root / ".tools/TripoSR", local_files_only=True)
            model.renderer.set_chunk_size(32768)
            with torch.inference_mode():
                embeddings = [renderer.pipe.encode_prompt(p, "cuda", 1, False)[0] for p in PROMPTS]
            anchor = Image.open(root / "assets/creature/realistic/guide.png").convert("RGBA")
            previous_image = None
            previous_field = None
            alignment = None
            sequence, errors, cleaned = 0, 0, 0
            path_position = 0.0
            previous_strength = .68
            while not stopping() and (not args.frames or sequence < args.frames):
                settings = {}
                try:
                    settings = json.loads((output / "settings.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                if settings.get("paused", False):
                    time.sleep(.1)
                    continue
                acknowledged = 0
                try:
                    acknowledged = int(json.loads((output / "ack.json").read_text()).get("sequence",0))
                except (OSError, ValueError):
                    pass
                # Three future states, plus the current state. Never overwrite a queued state.
                if not args.no_ack and sequence-acknowledged >= 3:
                    status("Буфер готов", sequence=sequence, queued=sequence-acknowledged)
                    time.sleep(.1)
                    continue
                tick = time.perf_counter()
                try:
                    sequence_next = sequence+1
                    step = float(np.clip(settings.get("motion", .12), .03, .3)) if sequence else 0.0
                    requested_strength = float(np.clip(settings.get("strength", .68), .5, .85))
                    strength = float(np.clip(requested_strength,previous_strength-.015,previous_strength+.015))
                    recovered = False
                    for attempt in range(5):
                        candidate_position = path_position+step
                        phase = candidate_position/2.16
                        index = int(phase) % len(PROMPTS)
                        blend = (phase % 1)**2*(3-2*(phase % 1))
                        renderer.settings.prompt = "neural_entity"
                        renderer.embeddings["neural_entity"] = embeddings[index]*(1-blend)+embeddings[(index+1)%4]*blend
                        status("Детальная генерация", sequence=sequence, queued=max(0,sequence-acknowledged))
                        # A clean identity anchor prevents recursive img2img from accumulating
                        # outlines and patterns. Adjacent noise/prompt coordinates change slowly.
                        image, diffusion = renderer.render(anchor, {"phase": candidate_position,
                            "coherence":0, "strength":strength, "guidance_scale":5.5})
                        continuity = image_continuity(previous_image,image)
                        if valid_silhouette(image) and continuity["accepted"]:
                            break
                        step *= .5
                        strength = (strength+previous_strength)*.5
                        recovered = True
                    else:
                        raise ValueError("Слишком резкая смена образа; предыдущий объём сохранён")
                    folder = output / f"field_{sequence_next:06d}"
                    folder.mkdir(exist_ok=True)
                    image.save(folder / "concept.png")
                    status("Нейросеть строит объём", sequence=sequence)
                    with torch.inference_mode():
                        code = model([prepare_image(folder / "concept.png")], device="cuda")[0]
                    resolution = int(settings.get("resolution", args.resolution))
                    if resolution not in (64, 80, 96, 128, 160, 192):
                        resolution = args.resolution
                    field, radius = sample_field(model, code, resolution)
                    sampled = time.perf_counter()
                    alignment = alignment or field_alignment(field, radius)
                    focus, amount = change_focus(previous_field, field, alignment)
                    comparison = compare_direct(model, code, field, folder) if args.compare_direct and sequence == 0 else {}
                    manifest = write_packet(folder, field, {
                        "sequence": sequence_next, "directory": str(folder), "seed": args.seed,
                        "seconds": time.perf_counter()-tick, "alignment": alignment,
                        "sampled_at_seconds":sampled-tick,
                        "focus": focus, "change": amount, "diffusion": diffusion,
                        "reconstruction": {"neural": True, "model": "stabilityai/TripoSR"},
                        "prompt_from": PROMPTS[index], "prompt_to": PROMPTS[(index+1)%4],
                        "prompt_mix": blend, "comparison": comparison, "continuity":continuity,
                        "path_position":candidate_position, "color_detail":"generated_front_projection",
                        "front_projection":front_projection(field,image),
                        "recovered_from_anchor": recovered,
                    })
                    atomic_json(output / "latest.json", manifest)
                    sequence = sequence_next
                    path_position, previous_strength = candidate_position, strength
                    atomic_json(output / "queue.json", {"schema":1, "generated":sequence,
                        "capacity":3, "packets":[{"sequence":n,"directory":str(output/f"field_{n:06d}")}
                        for n in range(max(1,acknowledged+1),sequence+1)]})
                    previous_image, previous_field = image, field
                    print(json.dumps({"sequence": sequence, "seconds": manifest["seconds"],
                                      "change": amount, "comparison": comparison}), flush=True)
                    status("Готов нейронный объём", sequence=sequence, seconds=manifest["seconds"])
                    errors = 0
                    # Keep current/previous data and every unconsumed state, regardless of
                    # how far generation has advanced. Paused playback cannot lose its queue.
                    if not args.no_ack:
                        while cleaned < acknowledged-2:
                            cleaned += 1
                            old = output / f"field_{cleaned:06d}"
                            for name in ("field.rgba", "field.json", "concept.png", "direct.png"):
                                (old / name).unlink(missing_ok=True)
                            if old.exists():
                                old.rmdir()
                except Exception as error:
                    errors += 1
                    status("Ошибка генерации", sequence=sequence, error=str(error))
                    if errors >= 3:
                        raise
                    torch.cuda.empty_cache()
                    time.sleep(.2)
            status("Поток остановлен", sequence=sequence)
    except Exception as error:
        status("Ошибка потока", error=str(error))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=217)
    parser.add_argument("--parent", type=int)
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--no-ack", action="store_true")
    parser.add_argument("--compare-direct", action="store_true")
    run(parser.parse_args())
