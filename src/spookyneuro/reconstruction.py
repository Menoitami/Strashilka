"""Real TripoSR inference with bounded-memory field sampling and CPU extraction.

TripoSR's optional torchmcubes extension is replaced only at the extraction boundary
with scikit-image marching cubes. The pretrained neural network is unmodified.
"""

import sys
import time
import types
from functools import partial
from pathlib import Path

import numpy as np
from PIL import Image

from .model_assets import DINO_MODEL, MODEL_REVISIONS

TRIPOSR_REVISION = MODEL_REVISIONS["stabilityai/TripoSR"]


def load_triposr(repository, device="cuda", local_files_only=False):
    import torch
    from huggingface_hub import hf_hub_download

    repository = Path(repository).resolve()
    if not (repository / "tsr/system.py").is_file():
        raise RuntimeError("TripoSR code is missing; run scripts/setup_3d.sh")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; pass --device cpu for slower reconstruction")
    if device == "cuda" and torch.cuda.mem_get_info()[0] < 2500 * 2**20:
        raise RuntimeError(
            "3D reconstruction needs at least 2500 MiB free VRAM; close other GPU jobs or use --device cpu"
        )

    # Match torchmcubes' z,y,x return convention; upstream helper reverses it.
    def marching_cubes(level, threshold):
        from skimage.measure import marching_cubes as extract

        vertices, faces, _, _ = extract(level.detach().cpu().numpy(), threshold)
        return torch.from_numpy(vertices[:, ::-1].copy()), torch.from_numpy(faces.copy()).long()

    extension = types.ModuleType("torchmcubes")
    extension.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = extension
    sys.path.insert(0, str(repository))
    from tsr.models.tokenizers import image as image_tokenizer
    from tsr.system import TSR

    # Upstream fetches the DINO config via an unpinned Hub call even when TSR's
    # own weights are local. Bind that dependency to the installed revision too.
    image_tokenizer.hf_hub_download = partial(
        hf_hub_download, revision=MODEL_REVISIONS[DINO_MODEL], local_files_only=local_files_only
    )
    config_path = hf_hub_download(
        "stabilityai/TripoSR", "config.yaml", revision=TRIPOSR_REVISION, local_files_only=local_files_only
    )
    hf_hub_download(
        "stabilityai/TripoSR", "model.ckpt", revision=TRIPOSR_REVISION, local_files_only=local_files_only
    )
    model = TSR.from_pretrained(
        str(Path(config_path).parent), config_name="config.yaml", weight_name="model.ckpt"
    )
    model.eval().to(device)
    model.renderer.set_chunk_size(4096)
    return model


def prepare_image(path):
    """An opaque input needs a mask, never silently reconstruct its background."""
    image = Image.open(path).convert("RGBA")
    alpha = np.asarray(image.getchannel("A"))
    if alpha.min() > 240:
        from rembg import new_session, remove

        image = remove(image, session=new_session("u2netp", providers=["CPUExecutionProvider"]))
        alpha = np.asarray(image.getchannel("A"))
    box = Image.fromarray(np.where(alpha > 32, 255, 0).astype(np.uint8)).getbbox()
    if box is None:
        raise ValueError("Input has no visible foreground")
    image = image.crop(box)
    side = int(max(image.size) / 0.85)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    rgb = Image.new("RGB", canvas.size, (128, 128, 128))
    rgb.paste(canvas, mask=canvas.getchannel("A"))
    return rgb.resize((512, 512), Image.Resampling.LANCZOS)


def reconstruct(source, repository, resolution=128, device="cuda", model=None):
    import torch
    import trimesh
    from skimage.measure import marching_cubes

    started = time.perf_counter()
    if model is None:
        model = load_triposr(repository, device)
    loaded = time.perf_counter()
    image = prepare_image(source)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        code = model([image], device=device)[0]
    encoded = time.perf_counter()
    radius = model.renderer.cfg.radius
    axis = np.linspace(-radius, radius, resolution, dtype=np.float32)
    # Keep the volume on CPU and feed bounded chunks. Do not allocate NxNxNx features on GPU.
    density = np.empty((resolution, resolution, resolution), dtype=np.float32)
    with torch.inference_mode():
        for i, x in enumerate(axis):
            yy, zz = np.meshgrid(axis, axis, indexing="ij")
            points = np.stack([np.full_like(yy, x), yy, zz], -1).reshape(-1, 3)
            query = model.renderer.query_triplane(model.decoder, torch.from_numpy(points).to(device), code)
            density[i] = query["density_act"].float().cpu().numpy().reshape(resolution, resolution)
        vertices, faces, _, _ = marching_cubes(
            density, level=25.0, spacing=(2 * radius / (resolution - 1),) * 3
        )
        vertices -= radius
        colors = (
            model.renderer.query_triplane(
                model.decoder, torch.tensor(vertices, dtype=torch.float32, device=device), code
            )["color"]
            .float()
            .cpu()
            .numpy()
        )
    mesh = trimesh.Trimesh(vertices, faces, vertex_colors=(colors * 255).astype(np.uint8), process=False)
    # TripoSR: x=depth, y=horizontal, z=up. Output: right-handed glTF Y-up, +Z facing.
    mesh.vertices = np.asarray(mesh.vertices)[:, [1, 2, 0]]
    components = mesh.split(only_watertight=False)
    if not components:
        raise ValueError("Reconstruction returned no surface")
    # Remove tiny floaters but retain detached fingers/horns if sufficiently large.
    cutoff = max(len(part.faces) for part in components) * 0.008
    mesh = trimesh.util.concatenate([part for part in components if len(part.faces) >= cutoff])
    if mesh.volume < 0:
        mesh.invert()
    low, high = mesh.bounds
    scale = 3.0 / (high[1] - low[1])
    mesh.vertices = (mesh.vertices - [(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2]) * scale
    elapsed = time.perf_counter() - started
    stats = {
        "model": "stabilityai/TripoSR",
        "model_revision": TRIPOSR_REVISION,
        "neural": True,
        "resolution": resolution,
        "device": device,
        "load_seconds": loaded - started,
        "encode_seconds": encoded - loaded,
        "total_seconds": elapsed,
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.faces),
        "peak_torch_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else 0,
        "source": str(Path(source).resolve()),
        "field_center_yup": [(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2],
        "field_scale": float(scale),
        "field_radius": float(radius),
    }
    return mesh, density, image, stats
