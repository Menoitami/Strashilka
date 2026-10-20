"""Reconstruct the photographic A-pose once; runtime continues to evolve it locally."""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from spookyneuro.mesh_export import density_morph, export_creature
from spookyneuro.reconstruction import reconstruct
from spookyneuro.rigging import humanoid_rig
from spookyneuro.runtime import gpu_job

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "assets/creature/realism-reference.png"
    output = ROOT / "assets/creature/realistic"
    output.mkdir(parents=True, exist_ok=True)
    names, parents, _ = humanoid_rig()
    positions = [[0, 1.38, 0], [0, 1.8, 0], [0, 2.2, 0], [0, 2.53, 0], [0, 2.75, 0]]
    for side in [-1, 1]:
        positions += [[side*.31, 2.3, 0], [side*.56, 1.87, .015], [side*.73, 1.4, .05]]
    for side in [-1, 1]:
        positions += [
            [side*.17, 1.4, 0], [side*.20, .78, 0], [side*.24, .12, .03], [side*.24, .05, .20]
        ]
    rig = [{"name": n, "parent": int(p), "position": v} for n, p, v in zip(names, parents, positions)]
    joints = output / "rig.json"
    joints.write_text(json.dumps(rig, indent=2))
    # Letterbox the transparent input without changing its proportions.
    reference = Image.open(source).convert("RGBA")
    alpha = np.asarray(reference.getchannel("A"))
    bounds = Image.fromarray((alpha > 128).astype("uint8")*255).getbbox()
    if bounds is None:
        raise ValueError("Reference has no subject")
    reference = reference.crop(bounds)
    scale = 512*.89/max(reference.size)
    reference = reference.resize(tuple(round(x*scale) for x in reference.size), Image.Resampling.LANCZOS)
    guide = Image.new("RGBA", (512, 512))
    guide.alpha_composite(reference, ((512-reference.width)//2, (512-reference.height)//2))
    guide.save(output / "guide.png")
    with gpu_job():
        mesh, density, _, stats = reconstruct(output / "guide.png", ROOT / ".tools/TripoSR", 192)
        mesh.export(output / "unrigged.ply")
        export_creature(mesh, output, stats, density_morph(mesh, density, stats), joints, legacy_payload=False)
    (output / "profile.json").write_text(json.dumps({
        "head_base_y": 2.52, "source": "../realism-reference.png",
        "description": "Photographic practical-effects prior; live geometry and textures remain diffusion-generated",
    }, indent=2))
    print(output, flush=True)


if __name__ == "__main__":
    build()
