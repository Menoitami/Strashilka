"""Stateful image conditioning and bounded, anatomy-anchored surface evolution."""

import cv2
import numpy as np
from PIL import Image

BODY_PROMPT = (
    "full length photograph of a single uncanny adult humanoid, practical horror film prosthetics, "
    "real human anatomy, asymmetric emaciated body, thin intact mottled skin over ribs, "
    "subtle swollen tendons, unsettling human face, sunken eyes, "
    "bald, ragged dark shorts, long arms, two legs, standing A pose, "
    "natural flesh, soft diffuse neutral light, plain dark background"
)


class TemporalGuide:
    """Evolve the last generated image with an OU field, retaining its changing silhouette.

    Absolute field is bounded around the anatomical guide; incremental remapping
    avoids an independent silhouette each frame and prevents cumulative mask erosion.
    """

    def __init__(self, anchor):
        self.anchor = np.asarray(anchor.convert("RGBA"))
        self.field = np.zeros(4, dtype=np.float32)

    def next(self, previous, rng, randomness=0.6, feedback=0.94):
        h, w = self.anchor.shape[:2]
        yy, xx = np.mgrid[:h, :w].astype(np.float32)
        basis = np.stack([np.exp(-(((yy / h - c) / 0.14) ** 2)) for c in [0.2, 0.42, 0.64, 0.82]])
        old_scale = 1 + np.einsum("i,ijk->jk", self.field, basis)
        self.field = np.clip(0.96 * self.field + rng.normal(0, 0.012, 4) * randomness, -0.16, 0.16)
        new_scale = 1 + np.einsum("i,ijk->jk", self.field, basis)
        anchor_x = (xx - w / 2) / new_scale + w / 2
        anchor = cv2.remap(self.anchor, anchor_x.astype("float32"), yy, cv2.INTER_LINEAR)
        if previous is None:
            return Image.fromarray(anchor)
        source = np.asarray(previous.convert("RGBA").resize((w, h)))
        previous_x = (xx - w / 2) * old_scale / new_scale + w / 2
        warped = cv2.remap(source, previous_x.astype("float32"), yy, cv2.INTER_LINEAR)
        warped[..., :3] = np.clip(feedback * warped[..., :3] + (1 - feedback) * anchor[..., :3], 0, 255)
        warped[..., 3] = anchor[..., 3]
        return Image.fromarray(warped)


def evolve_surface(previous, proposal, anchor, velocity=None, step_m=0.065, inertia=0.65):
    """Inertial target tracking, capped per vertex, with a fixed anatomical envelope.

    Zero step freezes geometry. The same operations on seam copies preserve welding.
    A convex envelope projection cannot increase the per-step bound if the previous
    state is inside it. Fixed feet keep the animated rig grounded.
    """
    previous, proposal, anchor = (np.asarray(v, dtype=np.float64) for v in (previous, proposal, anchor))
    velocity = np.zeros_like(previous) if velocity is None else velocity
    delta = inertia * velocity + (1 - inertia) * (proposal - previous) * 0.45
    grounded = np.clip((anchor[:, 1] - 0.08) / 0.35, 0, 1)
    limit = max(0, step_m) * grounded
    delta *= np.minimum(1, limit / np.maximum(np.linalg.norm(delta, axis=1), 1e-8))[:, None]
    following = previous + delta
    offset = following - anchor
    envelope = 0.42 * grounded
    offset *= np.minimum(1, envelope / np.maximum(np.linalg.norm(offset, axis=1), 1e-8))[:, None]
    following = anchor + offset
    return following.astype(np.float32), (following - previous).astype(np.float32)
