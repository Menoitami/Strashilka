import numpy as np
from PIL import Image

from spookyneuro.temporal import TemporalGuide, evolve_surface


def test_surface_is_bounded_over_long_random_trajectory_and_keeps_seams():
    rng = np.random.default_rng(42)
    anchor = rng.uniform([-0.5, 0, -0.3], [0.5, 3, 0.3], (500, 3)).astype("float32")
    anchor[1] = anchor[0]
    anchor[2, 1] = 0
    previous, velocity = anchor.copy(), None
    for _ in range(100):
        proposal = anchor + rng.normal(0, 0.6, anchor.shape)
        proposal[1] = proposal[0]
        following, velocity = evolve_surface(previous, proposal, anchor, velocity, step_m=0.065)
        assert np.linalg.norm(following - previous, axis=1).max() <= 0.065001
        assert np.linalg.norm(following - anchor, axis=1).max() <= 0.420001
        np.testing.assert_array_equal(following[0], following[1])
        np.testing.assert_array_equal(following[2], anchor[2])
        previous = following
    assert np.linalg.norm(previous - anchor, axis=1).mean() > 0.02
    frozen, _ = evolve_surface(previous, proposal, anchor, velocity, step_m=0)
    np.testing.assert_allclose(frozen, previous, atol=1e-7)


def test_guide_uses_previous_image_and_zero_randomness_preserves_silhouette():
    anchor = np.zeros((64, 64, 4), dtype="uint8")
    anchor[8:56, 24:40] = [160, 100, 80, 255]
    previous = anchor.copy()
    previous[..., :3] = [30, 60, 90]
    evolution = TemporalGuide(Image.fromarray(anchor))
    result = np.asarray(evolution.next(Image.fromarray(previous), np.random.default_rng(1), 0, 1))
    np.testing.assert_array_equal(result, previous)
    anchored = np.asarray(evolution.next(Image.fromarray(previous), np.random.default_rng(1), 0, 0))
    np.testing.assert_array_equal(anchored, anchor)


def test_guide_trajectory_is_reproducible_nonconstant_and_does_not_erode_mask():
    anchor = np.zeros((128, 128, 4), dtype="uint8")
    anchor[8:120, 40:88] = [160, 100, 80, 255]
    sequences = []
    for _ in range(2):
        evolution = TemporalGuide(Image.fromarray(anchor))
        rng = np.random.default_rng(1928)
        previous = None
        frames = []
        for _ in range(100):
            previous = evolution.next(previous, rng)
            frames.append(np.array(previous))
        sequences.append(frames)
    np.testing.assert_array_equal(sequences[0], sequences[1])
    assert not np.array_equal(sequences[0][0], sequences[0][-1])
    assert sequences[0][-1][..., 3].sum() > anchor[..., 3].sum() * 0.85
