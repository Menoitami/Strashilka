import io

import cv2
import numpy as np
from PIL import Image, ImageDraw


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def read_png(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        if image.width > 1024 or image.height > 1024:
            raise ValueError("Input image exceeds 1024 pixels")
        return image.convert("RGBA")


def proxy_image(size: int = 256) -> Image.Image:
    """Deterministic silhouette for the standalone benchmark (not training data)."""
    image = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(image)

    def box(coords):
        return tuple(int(v * size) for v in coords)

    d.ellipse(box((0.39, 0.07, 0.61, 0.3)), fill=(180, 155, 145, 255))
    d.ellipse(box((0.34, 0.27, 0.66, 0.65)), fill=(150, 120, 110, 255))
    for coords in [
        (0.25, 0.3, 0.36, 0.75),
        (0.64, 0.3, 0.75, 0.75),
        (0.35, 0.55, 0.47, 0.94),
        (0.53, 0.55, 0.65, 0.94),
    ]:
        d.rounded_rectangle(box(coords), radius=max(1, size // 25), fill=(160, 130, 120, 255))
    return image


def flow_fields(previous: Image.Image, current: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """DIS in both directions. Confidence uses round-trip consistency and bounds."""
    a, b = np.array(previous), np.array(current)
    gray_a = cv2.cvtColor(
        (a[:, :, :3].astype(np.float32) * (a[:, :, 3:4] / 255)).astype(np.uint8), cv2.COLOR_RGB2GRAY
    )
    gray_b = cv2.cvtColor(
        (b[:, :, :3].astype(np.float32) * (b[:, :, 3:4] / 255)).astype(np.uint8), cv2.COLOR_RGB2GRAY
    )
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
    forward = dis.calc(gray_a, gray_b, None)
    backward = dis.calc(gray_b, gray_a, None)
    h, w = gray_a.shape
    yy, xx = np.mgrid[:h, :w].astype(np.float32)

    def pack(flow, opposite):
        x, y = xx + flow[..., 0], yy + flow[..., 1]
        sampled = cv2.remap(opposite, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        error = np.linalg.norm(flow + sampled, axis=2)
        confidence = np.exp(-error / 1.5)
        confidence *= (x >= 0) & (x < w - 1) & (y >= 0) & (y < h - 1)
        result = np.zeros((h, w, 4), dtype="<f4")
        result[..., :2] = flow
        result[..., 2] = confidence
        return result

    return pack(forward, backward), pack(backward, forward)


def interpolate(a: Image.Image, b: Image.Image, t: float, fields=None) -> Image.Image:
    """CPU reference for the Godot shader; blend premultiplied colors."""
    t = float(np.clip(t, 0, 1))
    aa, bb = np.array(a).astype(np.float32) / 255, np.array(b).astype(np.float32) / 255
    aa[..., :3] *= aa[..., 3:4]
    bb[..., :3] *= bb[..., 3:4]
    baseline = aa * (1 - t) + bb * t
    if fields is not None:
        f, back = fields
        h, w = aa.shape[:2]
        yy, xx = np.mgrid[:h, :w].astype(np.float32)
        x1, y1 = xx - t * f[..., 0], yy - t * f[..., 1]
        x2, y2 = xx - (1 - t) * back[..., 0], yy - (1 - t) * back[..., 1]
        wa = cv2.remap(aa, x1, y1, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        wb = cv2.remap(bb, x2, y2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        confidence = np.minimum(f[..., 2], back[..., 2])[..., None]
        warped = wa * (1 - t) + wb * t
        baseline = baseline * (1 - confidence) + warped * confidence
    baseline[..., :3] /= np.maximum(baseline[..., 3:4], 1e-6)
    return Image.fromarray(np.uint8(np.clip(baseline * 255, 0, 255)))
