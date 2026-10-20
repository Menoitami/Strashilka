"""View-independent neural density/color caches; no mesh registration or rig.

Files contain uint8 RGBA in Godot Z/Y/X order. RGB is the decoder's color;
A is log1p(density)/log1p(128). World axes are (TripoSR y, z, x).
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

DENSITY_MAX = 128.0
PROMPTS = (
    ("full length studio photograph of an adult man in dark shorts, head and feet visible, "
     "realistic human face, detailed skin, front view, standing, soft neutral light, black background"),
    ("full length studio photograph of an adult man in dark shorts, head and feet visible, "
     "elongated asymmetric face, swollen uneven shoulders, detailed human skin, front view, standing, soft neutral light, black background"),
    ("full length studio photograph of an adult man in dark shorts, head and feet visible, "
     "elongated arms, incomplete extra arm emerging from shoulder, distorted human face, detailed skin, front view, standing, soft neutral light, black background"),
    ("full length studio photograph of an adult man in dark shorts, head and feet visible, "
     "melting human face, crooked torso, limbs merging into flesh, detailed skin, front view, standing, soft neutral light, black background"),
)


def image_continuity(previous, current):
    """Measure adjacent generated subjects, including silhouette and skin-color jumps."""
    if previous is None:
        return {"silhouette_iou": 1.0, "color_mae": 0.0, "accepted": True}
    a, b = [np.asarray(image.convert("RGBA").resize((128,128))) for image in (previous,current)]
    am, bm = a[...,3]>80, b[...,3]>80
    union, intersection = am|bm, am&bm
    iou = float(intersection.sum()/max(1,union.sum()))
    error = float(np.abs(a[intersection,:3].astype(float)-b[intersection,:3]).mean()/255) if intersection.any() else 1.0
    return {"silhouette_iou": iou, "color_mae": error, "accepted": iou>=.78 and error<=.16}


def front_projection(rgba, concept):
    """Map normalized volume XY to the generated image without camera-dependent views."""
    y,x = np.where((decode_density(rgba)>12).any(axis=0))
    iy,ix = np.where(np.asarray(concept.convert("RGBA"))[...,3]>80)
    sx = float(ix.max()-ix.min())/max(1,x.max()-x.min())/(concept.width-1)
    sy = float(iy.max()-iy.min())/max(1,y.max()-y.min())/(concept.height-1)
    return [sx*(rgba.shape[0]-1),float(ix.min())/(concept.width-1)-sx*x.min(),
            -sy*(rgba.shape[0]-1),float(iy.min())/(concept.height-1)+sy*y.max()]


def feedback_image(anchor, previous, retention=.15):
    """Blend image memory without restricting output to a predefined silhouette."""
    anchor = anchor.convert("RGBA").resize((384, 384))
    if previous is None:
        return anchor
    previous = previous.convert("RGBA").resize(anchor.size)
    # Composite against the same background before mixing to avoid transparent RGB fringes.
    def opaque(image):
        bg = Image.new("RGB", image.size, (8, 8, 8))
        bg.paste(image, mask=image.getchannel("A"))
        return bg
    image = Image.blend(opaque(anchor), opaque(previous), float(np.clip(retention, 0, 1)))
    image.putalpha(Image.new("L", image.size, 255))
    return image


def valid_silhouette(image):
    """Reject loss of the subject, but keep holes, extra limbs and anatomical errors."""
    mask = (np.asarray(image.convert("RGBA"))[..., 3] > 80).astype("uint8")
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if len(stats)<2:
        return False
    largest = stats[1:][np.argmax(stats[1:, cv2.CC_STAT_AREA])]
    area = float(mask.mean())
    return (.025 < area < .75 and largest[cv2.CC_STAT_AREA]/max(1,mask.sum()) > .45
            and largest[cv2.CC_STAT_HEIGHT] > mask.shape[0]*.45)


def encode_volume(density, color):
    if density.ndim != 3 or color.shape != (*density.shape, 3):
        raise ValueError("Expected Z/Y/X density and Z/Y/X/RGB color")
    if not np.isfinite(density).all() or not np.isfinite(color).all():
        raise ValueError("Non-finite neural field")
    alpha = np.log1p(np.clip(density, 0, DENSITY_MAX)) / np.log1p(DENSITY_MAX)
    return np.round(np.concatenate([np.clip(color, 0, 1), alpha[..., None]], -1)*255).astype("uint8")


def decode_density(rgba):
    return np.expm1(rgba[..., 3].astype("float32") / 255 * np.log1p(DENSITY_MAX))


def sample_field(model, code, resolution=192, device="cuda"):
    """Sample all three spatial axes, retaining disconnected neural components."""
    import torch

    if resolution not in (64, 80, 96, 128, 160, 192):
        raise ValueError("Unsupported field resolution")
    radius = float(model.renderer.cfg.radius)
    axis = np.linspace(-radius, radius, resolution, dtype=np.float32)
    density = np.empty((resolution,)*3, dtype=np.float32)
    color = np.empty((resolution,)*3+(3,), dtype=np.float32)
    # Slice z in Godot coordinates = x in the source model. Rows are y = source z.
    yy, xx = np.meshgrid(axis, axis, indexing="ij")
    with torch.inference_mode():
        for z, value in enumerate(axis):
            points = np.stack([np.full_like(xx, value), xx, yy], -1).reshape(-1, 3)
            result = model.renderer.query_triplane(
                model.decoder, torch.from_numpy(points).to(device), code,
            )
            density[z] = result["density_act"].float().cpu().numpy().reshape(resolution, resolution)
            color[z] = result["color"].float().cpu().numpy().reshape(resolution, resolution, 3)
    occupied = density > 12
    if occupied.sum() < 32 or occupied.mean() > .65:
        raise ValueError("Neural field is empty or fills the entire volume")
    return encode_volume(density, color), radius


def field_alignment(rgba, radius):
    """Choose scale once per session, never normalize every mutation separately."""
    z, y, x = np.where(decode_density(rgba) > 12)
    if not len(y):
        raise ValueError("Empty neural field")
    step = 2*radius/(rgba.shape[0]-1)
    low, high = y.min()*step-radius, y.max()*step-radius
    scale = 3.0/max(high-low, .25)
    center = [(float(x.min()+x.max())*.5*step-radius), low,
              (float(z.min()+z.max())*.5*step-radius)]
    return {"origin": center, "scale": scale, "radius": radius}


def change_focus(previous, current, alignment):
    """Find the location of actual density changes for local spatial effects."""
    if previous is None or previous.shape != current.shape:
        return [0.0, 1.8, 0.0], 0.0
    a, b = decode_density(previous), decode_density(current)
    weights = np.abs(np.minimum(a, 40)-np.minimum(b, 40))
    total = float(weights.sum())
    if total < 1e-5:
        return [0.0, 1.8, 0.0], 0.0
    indices = np.indices(a.shape, dtype=np.float32)
    xyz = np.array([(indices[i]*weights).sum()/total for i in (2, 1, 0)])
    xyz = xyz/(a.shape[0]-1)*2*alignment["radius"]-alignment["radius"]
    xyz = (xyz-np.asarray(alignment["origin"]))*alignment["scale"]
    return xyz.tolist(), float(np.clip(total/(a.size*1.5), 0, 1))


def write_packet(folder, rgba, metadata):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "field.rgba").write_bytes(rgba.tobytes(order="C"))
    manifest = {**metadata, "schema": 2, "representation": "neural_density_rgba8",
                "resolution": rgba.shape[0], "bytes": rgba.nbytes, "density_max": DENSITY_MAX}
    (folder / "field.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def compare_direct(model, code, rgba, output):
    """Measure direct neural ray rendering and compare cache queries to the decoder."""
    import torch
    from scipy.ndimage import map_coordinates

    radius = float(model.renderer.cfg.radius)
    rng = np.random.default_rng(4)
    xyz = rng.uniform(-radius*.8, radius*.8, (4096, 3)).astype("float32")
    with torch.inference_mode():
        exact = model.renderer.query_triplane(model.decoder, torch.from_numpy(xyz).cuda(), code)
    # Source xyz -> cache zyx = source xzy.
    coordinates = (xyz[:, [0, 2, 1]].T/radius+1)*.5*(rgba.shape[0]-1)
    cached_density = map_coordinates(decode_density(rgba), coordinates, order=1)
    exact_density = exact["density_act"].cpu().numpy().ravel()
    visible = exact_density > 5
    cached_rgb = np.stack([map_coordinates(rgba[..., c].astype("float32")/255,
                                          coordinates, order=1) for c in range(3)], -1)
    rgb_error = float(np.abs(cached_rgb[visible]-exact["color"].cpu().numpy()[visible]).mean())
    side = 128
    yy, xx = np.mgrid[:side, :side].astype("float32")
    # TripoSR +x is the front of the entity, source z points up.
    rays = np.stack([-np.ones_like(xx)*2.6, (xx/(side-1)-.5)*2,
                     (.5-yy/(side-1))*2], -1)
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    origins = np.broadcast_to(np.array([2.6, 0, 0], "float32"), rays.shape).copy()
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode():
        image = model.renderer(model.decoder, code, torch.from_numpy(origins).cuda(),
                               torch.from_numpy(rays).cuda())
    torch.cuda.synchronize()
    seconds = time.perf_counter()-start
    Image.fromarray((image.cpu().numpy().clip(0, 1)*255).astype("uint8")).save(output / "direct.png")
    return {"direct_resolution": side, "direct_seconds": seconds,
            "cache_rgb_mae": rgb_error,
            "cache_density_mae": float(np.abs(cached_density-exact_density.clip(0, DENSITY_MAX)).mean())}
