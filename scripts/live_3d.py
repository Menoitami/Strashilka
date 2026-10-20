"""Persistent SD + TripoSR worker. Every published state is new neural inference.

A single unacknowledged packet bounds memory/disk use and preserves A -> B continuity.
GPU models and UV rasterization stay resident; the game never waits for this process.
"""

import argparse
import json
import os
import shutil
import signal
import time
from pathlib import Path

import numpy as np
from PIL import Image


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False))
    temporary.replace(path)


def run(args):
    # The initial model-generation/setup step populates the cache. The in-game
    # worker must not hang on Hub metadata requests or silently download weights.
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    import trimesh
    import xatlas

    from spookyneuro.config import Settings
    from spookyneuro.mesh_export import export_creature, smooth_normals
    from spookyneuro.multiform import UVBaker, register_surface, sample_surface, tangent_frame
    from spookyneuro.reconstruction import load_triposr, reconstruct
    from spookyneuro.renderer import Renderer
    from spookyneuro.runtime import gpu_job
    from spookyneuro.temporal import BODY_PROMPT, TemporalGuide, evolve_surface
    from spookyneuro.texture_projection import (
        NeuralTexturePainter,
        TextureProjector,
        relief_from_paint,
        seed_reference_texture,
    )

    root = Path(__file__).resolve().parents[1]
    realistic = root / "assets/creature/realistic"
    base_directory = realistic if (realistic / "profile.json").is_file() else root / "artifacts/3d/generated"
    profile = json.loads((realistic / "profile.json").read_text()) if base_directory == realistic else {}
    joint_override = realistic / "rig.json" if profile else None
    os.chdir(root)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def status(stage, **extras):
        atomic_json(output / "status.json", {"stage": stage, "elapsed": time.monotonic() - started, **extras})

    def should_stop():
        if stopped or (output / "stop").exists():
            return True
        if args.parent:
            try:
                os.kill(args.parent, 0)
            except ProcessLookupError:
                return True
        return False

    def wait_ack(filename, sequence):
        while not args.no_ack and not should_stop():
            ack = output / filename
            try:
                if ack.exists() and int(json.loads(ack.read_text()).get("sequence", 0)) >= sequence:
                    return
            except (ValueError, OSError):
                pass
            time.sleep(0.05)

    try:
        with gpu_job():
            status("Загрузка диффузии")
            lora = root / "artifacts/body-horror-lora/lora"
            approved = root / "artifacts/body-horror-lora/approved.json"
            renderer = Renderer(
                Settings(
                    size=384,
                    steps=4,
                    strength=0.65,
                    mask_mode="fixed",
                    seed=args.seed,
                    lora=str(lora) if approved.exists() and lora.exists() else None,
                    lora_scale=0.55,
                ),
                local_files_only=True,
            )
            if should_stop():
                status("Поток остановлен")
                return
            torch.cuda.empty_cache()
            status("Загрузка 3D-нейросети")
            model = load_triposr(root / ".tools/TripoSR", local_files_only=True)
            if should_stop():
                status("Поток остановлен")
                return
            status("Подготовка общей поверхности")
            base = trimesh.load(base_directory / "unrigged.ply", force="mesh")
            base.merge_vertices(digits_vertex=3)
            base.update_faces(base.nondegenerate_faces(height=1e-5))
            base.remove_unreferenced_vertices()
            mapping, faces, uv = xatlas.parametrize(
                np.asarray(base.vertices, dtype=np.float32), np.asarray(base.faces, dtype=np.uint32)
            )
            mapping = np.asarray(mapping, dtype=int)
            vertices = np.asarray(base.vertices)[mapping]
            mesh = trimesh.Trimesh(
                vertices, faces, vertex_colors=np.asarray(base.visual.vertex_colors)[mapping], process=False
            )
            normals = smooth_normals(vertices, faces)
            tangent, _, sign = tangent_frame(vertices, faces, uv, normals)
            baker = UVBaker(faces, uv, size=1024)
            painter = NeuralTexturePainter(renderer, TextureProjector(baker, faces, uv))
            base_colors, _ = sample_surface(base, vertices)
            baker.bake(base_colors, np.tile([0, 0, 1.0], (len(vertices), 1)), output / "base")
            previous = vertices.copy()
            previous_maps = output / "base"
            guide_evolution = TemporalGuide(Image.open(
                realistic / "guide.png" if profile else root / "artifacts/3d/guide.png"
            ))
            previous_unique = np.asarray(base.vertices).copy()
            velocity = np.zeros_like(vertices)
            previous_texture = np.asarray(Image.open(output / "base_albedo.png"), dtype=np.float32) / 255
            if profile:
                previous_texture = seed_reference_texture(
                    painter.projector, vertices, normals, previous_texture,
                    Image.open(realistic / "guide.png").convert("RGBA"),
                )
                positions, _ = painter.projector.surface_pixels(vertices, normals)
                base_relief = relief_from_paint(previous_texture, positions)
                Image.fromarray((previous_texture*255).astype("uint8")).save(output / "base_albedo.png")
                Image.fromarray(((base_relief*.5+.5)*255).astype("uint8")).save(output / "base_normal.png")
            rng = np.random.default_rng(args.seed)
            sequence = 0
            face_sequence = 0
            previous_face_texture = previous_texture.copy()
            positions, directions = painter.projector.surface_pixels(vertices, normals)
            face_mask = np.clip((positions[..., 1]-profile.get("head_base_y", 2.25))/.14, 0, 1)
            face_mask *= np.clip((directions[..., 2]-.1)/.55, 0, 1)
            Image.fromarray((face_mask*255).astype("uint8")).save(output / "face_mask.png")

            def publish_face(source, body_sequence, seed, seconds, stats):
                nonlocal face_sequence
                face_sequence += 1
                folder = output / f"face_{face_sequence:06d}"
                folder.mkdir()
                for channel in ["albedo", "normal"]:
                    shutil.copyfile(source / f"next_{channel}.png", folder / f"{channel}.png")
                shutil.copyfile(output / "face_mask.png", folder / "mask.png")
                manifest = {
                    "sequence": face_sequence, "body_sequence": body_sequence,
                    "directory": str(folder), "seed": seed, "seconds": seconds,
                    "texture": stats, "independent_face": True, "extra": "front" not in stats,
                }
                atomic_json(folder / "face.json", manifest)
                atomic_json(output / "latest_face.json", manifest)
                print(json.dumps({"face_sequence": face_sequence, "body_sequence": body_sequence,
                                  "seconds": seconds}), flush=True)
                if face_sequence > 3:
                    shutil.rmtree(output / f"face_{face_sequence - 3:06d}", ignore_errors=True)

            errors = 0
            last_settings = {}
            previous_concept = None
            while not should_stop() and (not args.frames or sequence < args.frames):
                settings_path = output / "settings.json"
                if settings_path.exists():
                    try:
                        candidate = json.loads(settings_path.read_text())
                        if isinstance(candidate, dict):
                            last_settings = candidate
                    except (ValueError, OSError):
                        pass
                last_settings["head_base_y"] = profile.get("head_base_y", 2.25)
                chaos = float(np.clip(last_settings.get("randomness", 0.5), 0, 1))
                coherence = float(np.clip(last_settings.get("coherence", 0.9), 0, 0.95))
                feedback = float(np.clip(last_settings.get("feedback", 0.95), 0, 0.99))
                renderer.settings.strength = float(np.clip(last_settings.get("strength", 0.65), 0.5, 1))
                renderer.settings.size = int(last_settings.get("size", 384))
                if renderer.settings.size not in (256, 384, 512):
                    renderer.settings.size = 384
                resolution = int(last_settings.get("resolution", 96))
                if resolution not in (64, 96, 128):
                    resolution = 96
                renderer.settings.seed = int(rng.integers(0, 2**31 - 1))
                seed = renderer.settings.seed
                packet = output / f"frame_{sequence + 1:06d}"
                packet.mkdir(exist_ok=True)
                tick = time.monotonic()
                try:
                    status("Диффузия новой формы", sequence=sequence, seed=seed)
                    guide = guide_evolution.next(previous_concept, rng, chaos, feedback)
                    renderer.settings.prompt = BODY_PROMPT
                    # Bound the prompt cache during an indefinitely running session.
                    if len(renderer.embeddings) > 40:
                        renderer.embeddings.clear()
                    concept, diffusion_stats = renderer.render(
                        guide,
                        {
                            "phase": 0,
                            "coherence": coherence,
                            "lora_scale": float(np.clip(last_settings.get("body_horror", 0.2), 0, 1.2)),
                        },
                    )
                    concept.save(packet / "concept.png")
                    status("Реконструкция нового объёма", sequence=sequence, seed=seed)
                    target, _, _, reconstruction_stats = reconstruct(
                        packet / "concept.png", root / ".tools/TripoSR", resolution, model=model
                    )
                    status("Привязка поверхности и карт", sequence=sequence, seed=seed)
                    prior_mesh = trimesh.Trimesh(previous_unique, base.faces, process=False)
                    proposal = register_surface(prior_mesh, target)[mapping]
                    step_m = float(np.clip(last_settings.get("shape_step", 0.04), 0, 0.25))
                    fitted, next_velocity = evolve_surface(previous, proposal, vertices, velocity, step_m)
                    # Atlas seam copies map to the same source vertex.
                    next_unique = previous_unique.copy()
                    next_unique[mapping] = fitted
                    color, _detail_normals = sample_surface(target, fitted)
                    smooth = smooth_normals(fitted, faces)
                    # Direct per-pixel UV paint preserves eyes/lips instead of downsampling
                    # through TripoSR vertex colors. Mesh detail stays in the actual surface
                    # normals; noisy nearest-surface normal transfers used to cause facets.
                    normal = np.tile([0.0, 0.0, 1.0], (len(vertices), 1))
                    appearance_step = float(np.clip(last_settings.get("appearance_step", 0.85), 0, 1))
                    baker.bake(color, normal, packet / "next")
                    status("Диффузионная текстура тела и лица", sequence=sequence, seed=seed)
                    # Independent portraits retain their own last accepted appearance
                    # across body updates, in the same persistent UV coordinates.
                    paint_input = previous_texture*(1-face_mask[..., None])+previous_face_texture*face_mask[..., None]
                    painted, texture_stats = painter.paint(
                        fitted, smooth, paint_input, last_settings, seed, face_sequence, packet
                    )
                    Image.fromarray((painted * 255).astype(np.uint8)).save(packet / "next_albedo.png", compress_level=1)
                    for channel in ["albedo", "normal"]:
                        shutil.copyfile(
                            str(previous_maps) + "_" + channel + ".png", packet / f"previous_{channel}.png"
                        )
                        shutil.copyfile(output / f"base_{channel}.png", packet / f"base_{channel}.png")
                    export_creature(
                        mesh,
                        packet,
                        {},
                        joint_override=joint_override,
                        morph_targets=[("previous", previous - vertices), ("next", fitted - vertices)],
                        uvs=uv,
                        tangents=np.column_stack([tangent, sign]),
                        legacy_payload=False,
                    )
                    manifest = {
                        "schema": 1,
                        "forms": ["base", "previous", "next"],
                        "geometry_targets": ["previous", "next"],
                        "live": True,
                        "sequence": sequence + 1,
                        "seed": seed,
                        "seconds": time.monotonic() - tick,
                        "diffusion": diffusion_stats,
                        "reconstruction": reconstruction_stats,
                        "mean_change_m": float(np.linalg.norm(fitted - previous, axis=1).mean()),
                        "max_change_m": float(np.linalg.norm(fitted - previous, axis=1).max()),
                        "prompt": renderer.settings.prompt,
                        "coherence": coherence,
                        "feedback": feedback,
                        "shape_step_m": step_m,
                        "appearance_step": appearance_step,
                        "conditioning": "previous_concept_and_previous_mesh",
                        "texture": texture_stats,
                        "texture_method": "render_current_mesh_then_diffuse_then_visibility_project_to_uv",
                        "texture_resolution": 1024,
                        "base_profile": "realistic" if profile else "legacy",
                        "head_base_y": last_settings["head_base_y"],
                        "lora": renderer.settings.lora,
                        "lora_scale": renderer.settings.lora_scale,
                    }
                    atomic_json(packet / "forms.json", manifest)
                    publish_face(packet, sequence+1, seed, texture_stats["face"]["diffusion"].get("inference_ms", 0)/1000, texture_stats)
                    atomic_json(
                        output / "latest.json",
                        {"sequence": sequence + 1, "directory": str(packet), **manifest},
                    )
                    print(
                        json.dumps(
                            {
                                k: manifest[k]
                                for k in ["sequence", "seed", "seconds", "mean_change_m", "max_change_m"]
                            }
                        ),
                        flush=True,
                    )
                    sequence += 1
                    previous = fitted
                    previous_unique = next_unique
                    velocity = next_velocity
                    previous_texture = painted
                    previous_face_texture = painted
                    previous_concept = concept
                    previous_maps = packet / "next"
                    status("Готова новая форма", sequence=sequence, seconds=manifest["seconds"], seed=seed)
                    # Share the resident GPU models. Extra portraits skip body diffusion,
                    # reconstruction and GLB export, and can play during the body morph.
                    face_updates = int(np.clip(last_settings.get("face_updates", 3), 1, 6))
                    for _ in range(face_updates-1):
                        wait_ack("face_ack.json", face_sequence)
                        if should_stop():
                            break
                        face_seed = int(rng.integers(0, 2**31-1))
                        work = output / "face_work"
                        work.mkdir(exist_ok=True)
                        tick_face = time.monotonic()
                        status("Отдельная диффузия лица", sequence=sequence, face_sequence=face_sequence)
                        face_paint, face_stats = painter.paint(
                            fitted, smooth, previous_face_texture, last_settings,
                            face_seed, face_sequence, work, face_only=True,
                        )
                        Image.fromarray((face_paint*255).astype("uint8")).save(work / "next_albedo.png", compress_level=1)
                        publish_face(work, sequence, face_seed, time.monotonic()-tick_face, face_stats)
                        previous_face_texture = face_paint
                    wait_ack("face_ack.json", face_sequence)
                    # Never skip an endpoint: next packet starts at the last accepted target.
                    wait_ack("ack.json", sequence)
                    errors = 0
                    # Keep only recent packets; never delete the one the engine may be loading.
                    if sequence > 3:
                        shutil.rmtree(output / f"frame_{sequence - 3:06d}", ignore_errors=True)
                except Exception as error:
                    errors += 1
                    status("Ошибка генерации; повтор", error=str(error), sequence=sequence)
                    print(repr(error), flush=True)
                    if errors >= 3:
                        raise
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    time.sleep(0.25)
            status("Поток остановлен", sequence=sequence, face_sequence=face_sequence)
    except Exception as error:
        status("Ошибка потока", error=str(error))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=1928)
    parser.add_argument("--parent", type=int)
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument("--no-ack", action="store_true", help="Standalone benchmark only")
    run(parser.parse_args())
