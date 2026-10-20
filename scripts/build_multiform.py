"""Build a complete neural morph pack; publish ready.json only after every asset exists."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
import xatlas

from spookyneuro.mesh_export import export_creature
from spookyneuro.multiform import bake_maps, register_surface, sample_surface, tangent_frame
from spookyneuro.reconstruction import reconstruct
from spookyneuro.runtime import gpu_job

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="artifacts/3d/multiform")
parser.add_argument("--seed", type=int, default=1927)
parser.add_argument("--reuse-concepts", action="store_true")
parser.add_argument("--reuse-meshes", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
os.chdir(root)
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
(output / "ready.json").unlink(missing_ok=True)
started = time.monotonic()


def status(stage, error=None):
    content = {"stage": stage, "error": error, "seconds": time.monotonic() - started}
    temporary = output / "status.tmp"
    temporary.write_text(json.dumps(content))
    temporary.replace(output / "status.json")
    print(stage, flush=True)


try:
    status("Diffusion concepts")
    for name in ["swollen", "chitin"]:
        if not Path(f"artifacts/3d/guide_{name}.png").exists():
            subprocess.run(
                [
                    str(root / ".tools/godot"),
                    "--path",
                    "godot",
                    "--script",
                    "res://tools/export_concept.gd",
                    "--",
                    f"--variant={name}",
                ],
                check=True,
            )
    if not args.reuse_concepts:
        subprocess.run(
            [
                sys.executable,
                "scripts/concepts_multiform.py",
                "--output",
                str(output / "concepts"),
                "--seed",
                str(args.seed),
            ],
            check=True,
        )
    base = trimesh.load("artifacts/3d/generated/unrigged.ply", force="mesh")
    # Weld sub-millimetre slivers before fitting and unwrapping the shared topology.
    base.merge_vertices(digits_vertex=3)
    base.update_faces(base.nondegenerate_faces(height=1e-5))
    base.remove_unreferenced_vertices()
    targets = []
    for name in ["swollen", "chitin"]:
        status("Reconstructing " + name)
        cache = output / f"{name}.ply"
        if args.reuse_meshes and cache.exists():
            target = trimesh.load(cache, force="mesh")
        else:
            with gpu_job():
                target, _, _, stats = reconstruct(
                    output / "concepts" / f"{name}.png", root / ".tools/TripoSR", 192
                )
            target.export(cache)
            (output / f"{name}_reconstruction.json").write_text(json.dumps(stats, indent=2))
        targets.append(target)
    status("Registering neural surfaces")
    states = [np.asarray(base.vertices).copy()]
    for target in targets:
        states.append(register_surface(base, target))
    status("Shared UV atlas")
    mapping, faces, uvs = xatlas.parametrize(
        np.asarray(base.vertices, dtype=np.float32), np.asarray(base.faces, dtype=np.uint32)
    )
    meshes = [base, *targets]
    labels = ["skeletal", "swollen", "chitin"]
    mapping = np.asarray(mapping, dtype=int)
    mapped_states = [state[mapping] for state in states]
    atlas_mesh = trimesh.Trimesh(
        mapped_states[0], faces, vertex_colors=np.asarray(base.visual.vertex_colors)[mapping], process=False
    )
    base_tangent, _, sign = tangent_frame(mapped_states[0], faces, uvs, atlas_mesh.vertex_normals)
    metrics = []
    for i, label in enumerate(labels):
        status("Baking color and normals: " + label)
        position = mapped_states[i]
        fitted = trimesh.Trimesh(position, faces, process=False)
        colors, detail_normals = sample_surface(meshes[i], position)
        normal = fitted.vertex_normals
        tangent, bitangent, _ = tangent_frame(position, faces, uvs, normal)
        tangent_normal = np.column_stack(
            [
                np.sum(detail_normals * tangent, axis=1),
                np.sum(detail_normals * bitangent, axis=1),
                np.sum(detail_normals * normal, axis=1),
            ]
        )
        # Prevent noisy nearest-surface samples from producing inward-facing normals.
        tangent_normal[:, 2] = np.maximum(tangent_normal[:, 2], 0.35)
        tangent_normal /= np.maximum(np.linalg.norm(tangent_normal, axis=1, keepdims=True), 1e-7)
        coverage = bake_maps(faces, uvs, colors, tangent_normal, output / label)
        movement = np.linalg.norm(position - mapped_states[0], axis=1)
        metrics.append(
            {
                "name": label,
                "mean_displacement_m": float(movement.mean()),
                "p95_displacement_m": float(np.percentile(movement, 95)),
                "max_displacement_m": float(movement.max()),
                "uv_coverage": coverage,
            }
        )
    status("Exporting animated morph pack")
    deltas = [(labels[i], mapped_states[i] - mapped_states[0]) for i in (1, 2)]
    metadata = {"model": "SD1.5 + LCM + TripoSR", "seed": args.seed, "neural": True, "forms": metrics}
    export_creature(
        atlas_mesh,
        output,
        metadata,
        morph_targets=deltas,
        uvs=uvs,
        tangents=np.column_stack([base_tangent, sign]),
    )
    manifest = {
        "schema": 1,
        "forms": labels,
        "geometry_targets": ["swollen", "chitin"],
        "seed": args.seed,
        "metrics": metrics,
        "seconds": time.monotonic() - started,
        "provenance": "Diffusion concepts -> TripoSR 3D reconstructions -> common-topology registration; normals baked from reconstructed surface normals",
    }
    (output / "forms.json").write_text(json.dumps(manifest, indent=2))
    status("Ready")
    (output / "ready.json").write_text(json.dumps(manifest, indent=2))
except Exception as error:
    status("Failed", str(error))
    raise
