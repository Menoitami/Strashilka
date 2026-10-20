"""Flow in one canonical portrait, never across disconnected UV islands."""

import cv2
import numpy as np
from PIL import Image

from .imaging import flow_fields
from .texture_projection import face_view


def write_face_transition(projector, vertices, normals, previous, current, head_base, folder):
    view = face_view(vertices, head_base)
    portraits = []
    for label, texture in (("previous", previous), ("next", current)):
        portrait, _ = projector.render(vertices, normals, texture * 255, view, 256)
        portrait.save(folder / f"portrait_{label}.png")
        portraits.append(portrait)
    for label, field in zip(("forward", "backward"), flow_fields(*portraits), strict=True):
        # 32 pixels is the representable displacement; reject larger or uncovered flow.
        index = 0 if label == "forward" else 1
        alpha = np.asarray(portraits[index])[..., 3].astype(np.float32) / 255
        other_alpha = np.asarray(portraits[1-index])[..., 3].astype(np.float32) / 255
        yy, xx = np.mgrid[:256, :256].astype(np.float32)
        covered = cv2.remap(other_alpha, xx+field[..., 0], yy+field[..., 1], cv2.INTER_LINEAR)
        confidence = field[..., 2] * alpha * covered * (np.abs(field[..., :2]).max(-1) < 31.75)
        packed = np.dstack([np.clip(np.rint(field[..., :2]*4+128), 0, 255), confidence*255])
        Image.fromarray(packed.astype("uint8")).save(folder / f"flow_{label}.png")
    return [float(view.center_x), float(view.center_y), float(view.span)]
