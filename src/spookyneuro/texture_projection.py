"""Paint a skinned creature in image space, then project pixels into its persistent UV atlas.

All views are rendered from the actual current mesh and previous texture. Visibility
uses a triangle z-buffer; faces are never projected through the skull onto its back.
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numba import njit
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .mutation import face_detail


@dataclass
class View:
    center_x: float
    center_y: float
    span: float
    direction: float = 1.0

    def project(self, points, size):
        p = np.asarray(points)
        x = ((p[..., 0] * self.direction - self.center_x) / self.span + 0.5) * (size - 1)
        y = (0.5 - (p[..., 1] - self.center_y) / self.span) * (size - 1)
        return np.stack([x, y, p[..., 2] * self.direction], -1).astype(np.float32)


def body_view(vertices, direction=1.0):
    lo, hi = np.min(vertices, 0), np.max(vertices, 0)
    return View(
        (lo[0] + hi[0]) * 0.5 * direction,
        (lo[1] + hi[1]) * 0.5,
        max(hi[0] - lo[0], hi[1] - lo[1]) * 1.12,
        direction,
    )


def face_view(vertices, head_base=2.25):
    head = vertices[vertices[:, 1] > head_base+.03]
    if len(head) < 3:
        raise ValueError("No anatomical head region for face painting")
    lo, hi = head.min(0), head.max(0)
    return View((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, max(hi[0] - lo[0], hi[1] - lo[1]) * 1.18)


@njit(cache=True)
def rasterize(projected, faces, uv, normals, texture, size):
    depth = np.full((size, size), -1e10, np.float32)
    rgba = np.zeros((size, size, 4), np.uint8)
    for face in faces:
        a, b, c = projected[face[0]], projected[face[1]], projected[face[2]]
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-8:
            continue
        xmin = max(0, int(np.floor(min(a[0], b[0], c[0]))))
        xmax = min(size - 1, int(np.ceil(max(a[0], b[0], c[0]))))
        ymin = max(0, int(np.floor(min(a[1], b[1], c[1]))))
        ymax = min(size - 1, int(np.ceil(max(a[1], b[1], c[1]))))
        for y in range(ymin, ymax + 1):
            for x in range(xmin, xmax + 1):
                wa = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / den
                wb = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / den
                wc = 1 - wa - wb
                if min(wa, wb, wc) < -0.0001:
                    continue
                z = wa * a[2] + wb * b[2] + wc * c[2]
                if z <= depth[y, x]:
                    continue
                depth[y, x] = z
                u = wa * uv[face[0], 0] + wb * uv[face[1], 0] + wc * uv[face[2], 0]
                v = wa * uv[face[0], 1] + wb * uv[face[1], 1] + wc * uv[face[2], 1]
                tx = min(texture.shape[1] - 1, max(0, int(u * (texture.shape[1] - 1))))
                ty = min(texture.shape[0] - 1, max(0, int(v * (texture.shape[0] - 1))))
                n = wa * normals[face[0]] + wb * normals[face[1]] + wc * normals[face[2]]
                # Subtle geometry shading, strong enough for img2img without baking hard lights.
                light = 0.82 + 0.18 * max(0.0, n[1] * 0.45 + abs(n[2]) * 0.85)
                for channel in range(3):
                    rgba[y, x, channel] = min(255, int(texture[ty, tx, channel] * light))
                rgba[y, x, 3] = 255
    return rgba, depth


class TextureProjector:
    def __init__(self, baker, faces, uv):
        self.baker, self.faces, self.uv = baker, faces, uv

    def render(self, vertices, normals, texture, view, size=384):
        rgba, depth = rasterize(
            view.project(vertices, size),
            np.asarray(self.faces, np.int32),
            np.asarray(self.uv, np.float32),
            np.asarray(normals, np.float32),
            np.asarray(texture, np.uint8),
            size,
        )
        return Image.fromarray(rgba), depth

    def surface_pixels(self, vertices, normals):
        indices, weights = self.baker.indices, self.baker.weights[..., None]
        positions = (vertices[indices] * weights).sum(2).astype(np.float32)
        directions = (normals[indices] * weights).sum(2).astype(np.float32)
        directions /= np.maximum(np.linalg.norm(directions, axis=-1, keepdims=True), 1e-7)
        return positions, directions

    def project(self, image, depth, view, positions, directions, face_only=False, head_base=2.25):
        size = depth.shape[0]
        projected = view.project(positions, size)
        x, y, z = projected[..., 0], projected[..., 1], projected[..., 2]
        valid = (x >= 0) & (y >= 0) & (x < size - 1) & (y < size - 1)
        # Fill raster pinholes only for depth lookup. Reject silhouettes using original alpha below.
        foreground = depth > -1e9
        if not foreground.any():
            return np.zeros_like(positions), np.zeros(positions.shape[:2], np.float32)
        nearest = distance_transform_edt(~foreground, return_distances=False, return_indices=True)
        filled = depth[nearest[0], nearest[1]]
        front_z = cv2.remap(filled, x, y, cv2.INTER_LINEAR)
        visibility = (np.abs(front_z - z) < 0.025) & valid
        array = np.asarray(image.convert("RGBA"))
        color = cv2.remap(array[..., :3], x, y, cv2.INTER_LINEAR).astype(np.float32) / 255
        alpha = cv2.remap(array[..., 3], x, y, cv2.INTER_LINEAR).astype(np.float32) / 255
        facing = np.clip((directions[..., 2] * view.direction - 0.1) / 0.55, 0, 1)
        confidence = visibility * facing * alpha
        if face_only:
            # Feather at the jaw/temples; no rectangular portrait border on the body.
            confidence *= np.clip((positions[..., 1] - head_base) / 0.14, 0, 1)
            radius = ((x / (size - 1) - 0.5) / 0.50) ** 2 + ((y / (size - 1) - 0.5) / 0.56) ** 2
            confidence *= np.clip((1 - radius) * 4, 0, 1)
        return color, confidence.astype(np.float32)


def combine_views(previous, layers, amount=1.0):
    """Normalized visibility blending; a black pixel is valid paint, never a missing pixel."""
    total = sum(weight for _, weight in layers)
    weighted = sum(color * weight[..., None] for color, weight in layers)
    fresh = weighted / np.maximum(total[..., None], 1e-7)
    blend = np.clip(total, 0, 1) * amount
    return previous * (1 - blend[..., None]) + fresh * blend[..., None]


def seed_reference_texture(projector, vertices, normals, previous, reference):
    """Project the canonical photographic front once; keep unseen TripoSR color intact."""
    view = body_view(vertices)
    guide, depth = projector.render(vertices, normals, previous*255, view, 512)
    box = guide.getbbox()
    alpha = np.asarray(reference.getchannel("A"))
    source_box = Image.fromarray((alpha > 128).astype("uint8")*255).getbbox()
    if box is None or source_box is None:
        return previous
    aligned = Image.new("RGBA", (512, 512))
    subject = reference.crop(source_box).resize((box[2]-box[0], box[3]-box[1]), Image.Resampling.LANCZOS)
    aligned.alpha_composite(subject, (box[0], box[1]))
    positions, directions = projector.surface_pixels(vertices, normals)
    color, confidence = projector.project(aligned, depth, view, positions, directions)
    return combine_views(previous, [(color, confidence)]).astype(np.float32)


def preserve_skin_tone(candidate, anchor, limit=.16):
    """Bound cumulative pigment drift while retaining neural wrinkles and mottling."""
    return np.clip(anchor+limit*np.tanh((candidate-anchor)/limit), 0, 1).astype(np.float32)


def preserve_face_tone(candidate, anchor):
    """Keep moving eyes/lips in luminance, but constrain cumulative neon chroma."""
    weights = np.array([.2126, .7152, .0722], np.float32)
    light = (candidate*weights).sum(-1, keepdims=True)
    anchor_light = (anchor*weights).sum(-1, keepdims=True)
    chroma = candidate-light
    anchor_chroma = anchor-anchor_light
    chroma = anchor_chroma+.045*np.tanh((chroma-anchor_chroma)/.045)
    return np.clip(.04+.86*light+chroma, 0, 1).astype(np.float32)


FACE_STATES = [
    "gaunt adult human face, deep set tired eyes, sharp nose, parted dry lips, taut cheek tendons",
    "asymmetrical human face, one drooping eyelid, strained half smile, swollen cheek, fine wrinkles",
    "anguished human face, unfocused staring eyes, slack jaw, lips slightly open, stretched folds",
    "aged human face, squinting eyes, crooked tense mouth, leathery wrinkled cheeks",
    "uncanny human face, cloudy eyes, closed cracked lips, asymmetrical swelling, sinewy neck",
]
FACE_PREFIX = "close up RAW photograph of an uncanny adult face in practical horror film makeup, "
FACE_SUFFIX = ", realistic pale skin pores and capillaries, moist eyes, natural flesh, fine imperfections, bald, frontal face, soft neutral diffuse light"
BODY_TEXTURE_PROMPT = (
    "full body RAW photograph of an uncanny gaunt adult humanoid in practical horror makeup, "
    "intact sallow human skin over subtle ribs and tendons, natural mottled pigmentation, "
    "fine veins and wrinkles, slight bruising, ragged dark shorts, "
    "real flesh, soft neutral diffuse lighting, dark background"
)


class NeuralTexturePainter:
    """Independent latent histories for body/front, back and close-up face; one resident SD pipeline."""

    def __init__(self, renderer, projector):
        self.renderer, self.projector = renderer, projector
        self.noises = {}
        self.anchor = None

    def paint(self, vertices, normals, previous, settings, seed, sequence, output, face_only=False):
        from dataclasses import replace

        renderer = self.renderer
        saved_settings, saved_noise = renderer.settings, renderer.temporal_noise
        positions, directions = self.projector.surface_pixels(vertices, normals)
        layers, stats = [], {}
        if self.anchor is None:
            self.anchor = previous.copy()
        face_state = FACE_STATES[sequence % len(FACE_STATES)] + ", " + face_detail(seed)
        head_base = float(settings.get("head_base_y", 2.25))
        face_size = int(settings.get("face_size", 512))
        face_size = face_size if face_size in (384, 512) else 512
        texture_steps = int(settings.get("texture_steps", 6))
        texture_steps = texture_steps if texture_steps in (4, 6, 8) else 6
        stability = float(np.clip(settings.get("color_stability", 1), 0, 1))
        try:
            views = [
                ("front", body_view(vertices)),
                ("back", body_view(vertices, -1)),
                ("face", face_view(vertices, head_base)),
            ]
            if face_only:
                views = views[-1:]
            for name, view in views:
                face = name == "face"
                # The stable photographic surface resists cumulative stylization.
                feedback = .75 if face else .65
                pixels = np.clip((previous*feedback+self.anchor*(1-feedback))*255, 0, 255).astype(np.uint8)
                guide, depth = self.projector.render(vertices, normals, pixels, view, face_size if face else 384)
                guide.save(output / f"texture_{name}_guide.png", compress_level=1)
                renderer.settings = replace(
                    saved_settings,
                    size=face_size if face else 384,
                    steps=texture_steps,
                    seed=(seed + {"front": 173, "back": 521, "face": 1297}[name]) % (2**31 - 1),
                    strength=float(
                        settings.get("face_strength", 0.64) if face else settings.get("texture_strength", 0.45)
                    ),
                    prompt=FACE_PREFIX + face_state + FACE_SUFFIX
                    if face
                    else BODY_TEXTURE_PROMPT
                    + (" rear view, back muscles, back of head" if name == "back" else ", front view"),
                )
                renderer.temporal_noise = self.noises.get(name)
                image, inference = renderer.render(
                    guide,
                    {
                        "phase": 0,
                        "coherence": 0.72 if face else 0.82,
                        "lora_scale": min(.16, float(settings.get("body_horror", .2))) if face
                        else float(settings.get("body_horror", .2)),
                    },
                )
                self.noises[name] = renderer.temporal_noise
                image.save(output / f"texture_{name}.png", compress_level=1)
                color, confidence = self.projector.project(image, depth, view, positions, directions, face, head_base)
                stable = preserve_face_tone(color, self.anchor) if face else preserve_skin_tone(color, self.anchor)
                color = color*(1-stability)+stable*stability
                stats[name] = {"diffusion": inference, "coverage": float((confidence > 0.1).mean())}
                if face:
                    painted = previous if face_only else combine_views(
                        previous, layers, float(settings.get("appearance_step", 0.85))
                    )
                    painted = combine_views(
                        painted, [(color, confidence)], float(settings.get("face_amount", 1.0))
                    )
                else:
                    layers.append((color, confidence))
            stats["face_prompt"] = face_state
            stats["mean_rgb_change"] = float(np.abs(painted - previous).mean())
            face_mask = (positions[..., 1] > head_base+.05) & (directions[..., 2] > 0.3)
            stats["face_rgb_change"] = (
                float(np.abs(painted - previous)[face_mask].mean()) if face_mask.any() else 0.0
            )
            normal = relief_from_paint(painted, positions)
            Image.fromarray(np.clip((normal * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)).save(
                output / "next_normal.png", compress_level=1
            )
            return np.clip(painted, 0, 1).astype(np.float32), stats
        finally:
            renderer.settings, renderer.temporal_noise = saved_settings, saved_noise
            renderer._set_adapters()


def relief_from_paint(color, positions, height_m=0.0015):
    """Subtle contrast-derived microrelief, not inferred metric depth.

    Reject gradients crossing atlas islands by testing world-space continuity.
    Geometry normals still provide the large anatomical shape.
    """
    luminance = np.sum(color * np.array([0.2126, 0.7152, 0.0722], np.float32), -1)
    fine = cv2.GaussianBlur(luminance, (0, 0), 0.8)
    height = (fine - cv2.GaussianBlur(fine, (0, 0), 4)) * height_m
    dy, dx = np.gradient(height)
    py, px = np.gradient(positions, axis=(0, 1))
    sx, sy = np.linalg.norm(px, axis=-1), np.linalg.norm(py, axis=-1)
    valid_x = (sx > 1e-5) & (sx < 0.025)
    valid_y = (sy > 1e-5) & (sy < 0.025)
    nx = -np.clip(dx / np.maximum(sx, 1e-5), -0.35, 0.35) * valid_x
    ny = -np.clip(dy / np.maximum(sy, 1e-5), -0.35, 0.35) * valid_y
    normal = np.stack([nx, ny, np.ones_like(nx)], -1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal.astype(np.float32)
