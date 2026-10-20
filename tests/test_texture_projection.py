import numpy as np
from PIL import Image

from spookyneuro.multiform import UVBaker
from spookyneuro.texture_projection import TextureProjector, View, combine_views, relief_from_paint


def planes():
    vertices = np.array(
        [
            [-1, -1, 0.2],
            [1, -1, 0.2],
            [-1, 1, 0.2],
            [1, 1, 0.2],
            [-1, -1, -0.2],
            [1, -1, -0.2],
            [-1, 1, -0.2],
            [1, 1, -0.2],
        ]
    )
    faces = np.array([[0, 1, 2], [2, 1, 3], [4, 5, 6], [6, 5, 7]])
    uv = np.array([[0, 0], [0.4, 0], [0, 1], [0.4, 1], [0.6, 0], [1, 0], [0.6, 1], [1, 1]])
    normals = np.array([[0, 0, 1]] * 4 + [[0, 0, -1]] * 4, dtype=float)
    return vertices, faces, uv, normals


def test_projection_retains_pixel_detail_and_does_not_paint_through_mesh():
    vertices, faces, uv, normals = planes()
    painter = TextureProjector(UVBaker(faces, uv, 128), faces, uv)
    view = View(0, 0, 2.2)
    guide, depth = painter.render(vertices, normals, np.full((128, 128, 3), 200, np.uint8), view, 128)
    yy, xx = np.mgrid[:128, :128]
    color = np.stack([((xx // 6) % 2) * 255, yy * 2, xx * 2], -1).astype("uint8")
    image = np.dstack([color, np.array(guide)[..., 3]])
    positions, directions = painter.surface_pixels(vertices, normals)
    projected, confidence = painter.project(Image.fromarray(image), depth, view, positions, directions)
    previous = np.full((128, 128, 3), 0.6)
    result = combine_views(previous, [(projected, confidence)])
    # Four vertices cannot encode these stripes; this verifies per-texel detail.
    assert np.ptp(result[64, 5:45, 0]) > 0.9
    assert (np.diff(result[64, 5:45, 0]) > 0.4).sum() >= 4
    np.testing.assert_array_equal(result[:, 85:], previous[:, 85:])
    # The upward (+Y) world side samples the top of the source image, not its bottom.
    assert result[12, 20, 1] > result[110, 20, 1]
    # Even incorrect back normals cannot bypass the depth visibility check.
    directions[..., 2] = 1
    _, visible = painter.project(Image.fromarray(image), depth, view, positions, directions)
    assert visible[:, 85:].max() == 0


def test_black_paint_is_valid_and_zero_amount_freezes_texture():
    previous = np.ones((8, 8, 3), np.float32)
    black, weight = np.zeros_like(previous), np.ones((8, 8), np.float32)
    np.testing.assert_array_equal(combine_views(previous, [(black, weight)], 0), previous)
    np.testing.assert_array_equal(combine_views(previous, [(black, weight)], 1), black)


def test_skin_tone_does_not_accumulate_neon_drift():
    from spookyneuro.texture_projection import preserve_skin_tone

    anchor = np.full((16, 16, 3), [.58, .46, .39], np.float32)
    previous = anchor.copy()
    for _ in range(40):
        previous = preserve_skin_tone(previous+[.2, -.3, .4], anchor)
    assert np.abs(previous-anchor).max() <= .160001
    assert np.isfinite(previous).all()
    small_change = preserve_skin_tone(anchor+.025, anchor)
    assert (small_change-anchor).min() > .024
    np.testing.assert_array_equal(anchor, np.full_like(anchor, [.58, .46, .39]))


def test_face_palette_stays_flesh_colored_without_freezing_eyes_and_mouth():
    from spookyneuro.texture_projection import preserve_face_tone

    anchor = np.full((16, 16, 3), [.58, .46, .39], np.float32)
    previous = anchor.copy()
    weights = np.array([.2126, .7152, .0722])
    anchor_chroma = anchor-(anchor*weights).sum(-1, keepdims=True)
    for _ in range(40):
        previous = preserve_face_tone(np.clip(previous+[-.3, .25, .4], 0, 1), anchor)
        chroma = previous-(previous*weights).sum(-1, keepdims=True)
        assert np.abs(chroma-anchor_chroma).max() < .09
    # Black eyes / a mouth can move away from the reference's feature locations.
    white = np.full_like(anchor, .85)
    white[6:9, 4:12] = .02
    face = preserve_face_tone(white, anchor)
    assert face[0, 0].mean()-face[7, 8].mean() > .6
    assert np.isfinite(previous).all()


def test_photographic_seed_is_projected_only_onto_visible_front():
    from spookyneuro.texture_projection import seed_reference_texture

    vertices, faces, uv, normals = planes()
    projector = TextureProjector(UVBaker(faces, uv, 64), faces, uv)
    previous = np.full((64, 64, 3), .4, np.float32)
    result = seed_reference_texture(
        projector, vertices, normals, previous, Image.new("RGBA", (64, 64), (210, 140, 110, 255))
    )
    assert result[32, 12, 0] > .8
    np.testing.assert_array_equal(result[:, 45:], previous[:, 45:])
    np.testing.assert_array_equal(previous, np.full_like(previous, .4))

def test_relief_normals_are_unit_length_and_reject_island_edges():
    yy, xx = np.mgrid[:64, :64].astype("float32")
    positions = np.stack([xx * 0.005, yy * 0.005, xx * 0], -1)
    positions[:, 32:, 0] += 2
    color = np.repeat((xx / 64)[..., None], 3, -1)
    normal = relief_from_paint(color, positions)
    np.testing.assert_allclose(np.linalg.norm(normal, axis=-1), 1, atol=1e-6)
    assert np.isfinite(normal).all()
    np.testing.assert_array_equal(normal[:, 31:33, 0], 0)
    flat = relief_from_paint(np.ones_like(color) * 0.5, positions)
    np.testing.assert_allclose(flat, np.broadcast_to([0, 0, 1], flat.shape), atol=1e-6)


def test_painter_preserves_shape_diffusion_state_and_uses_separate_histories(tmp_path):
    from spookyneuro.config import Settings
    from spookyneuro.texture_projection import NeuralTexturePainter

    class FakeRenderer:
        def __init__(self):
            self.settings = Settings()
            self.temporal_noise = "geometry"
            self.calls = []

        def render(self, guide, metadata):
            self.calls.append((self.temporal_noise, self.settings.prompt))
            self.temporal_noise = len(self.calls)
            image = np.array(guide)
            image[..., :3] = [180, 80, 70]
            return Image.fromarray(image), {"mock": True}

        def _set_adapters(self):
            pass

    vertices, faces, uv, normals = planes()
    vertices[:, 1] += 2.5
    projector = TextureProjector(UVBaker(faces, uv, 64), faces, uv)
    renderer = FakeRenderer()
    original_settings = renderer.settings
    painter = NeuralTexturePainter(renderer, projector)
    previous = np.full((64, 64, 3), 0.4, np.float32)
    result, stats = painter.paint(vertices, normals, previous, {}, 55, 0, tmp_path)
    assert renderer.settings is original_settings and renderer.temporal_noise == "geometry"
    assert [noise for noise, _ in renderer.calls] == [None, None, None]
    painter.paint(vertices, normals, result, {}, 56, 1, tmp_path)
    assert [noise for noise, _ in renderer.calls[3:]] == [1, 2, 3]
    assert renderer.temporal_noise == "geometry"
    assert renderer.calls[2][1] != renderer.calls[5][1]
    assert stats["face_rgb_change"] > 0
    np.testing.assert_array_equal(previous, np.full_like(previous, 0.4))
    assert (tmp_path / "next_normal.png").exists()
    # An extra portrait uses only its own latent history and leaves the torso intact.
    prior = result.copy()
    face, face_stats = painter.paint(vertices, normals, prior, {}, 57, 2, tmp_path, face_only=True)
    assert len(renderer.calls) == 7 and renderer.calls[-1][0] == 6
    assert painter.noises["front"] == 4 and painter.noises["back"] == 5
    assert renderer.temporal_noise == "geometry" and renderer.settings is original_settings
    assert "front" not in face_stats and "back" not in face_stats
    positions, _ = projector.surface_pixels(vertices, normals)
    np.testing.assert_array_equal(face[positions[..., 1] < 2.25], prior[positions[..., 1] < 2.25])
    assert face_stats["face_rgb_change"] > 0
