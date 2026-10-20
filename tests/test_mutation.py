import json

import numpy as np
from PIL import Image

from spookyneuro.face_transition import write_face_transition
from spookyneuro.multiform import UVBaker
from spookyneuro.mutation import FAMILIES, mutation_plan
from spookyneuro.texture_projection import TextureProjector


def test_plans_are_reproducible_bounded_and_cover_anatomy_families():
    seen = set()
    for sequence in range(12):
        plan = mutation_plan(1928, sequence)
        assert plan == mutation_plan(1928, sequence)
        seen.add(plan["family"])
        assert len(plan["modules"]) <= 5
        assert len({module["slot"] for module in plan["modules"]}) == len(plan["modules"])
        assert all(-1 <= value <= 1 for value in plan["face"])
        assert all(.5 <= module["scale"] <= 2 for module in plan["modules"])
    assert seen == set(FAMILIES)
    assert mutation_plan(1928, 1)["face"] != mutation_plan(9281, 1)["face"]


def test_face_flow_uses_canonical_portrait_and_rejects_background(tmp_path):
    vertices = np.array([[-.3, 2.3, .2], [.3, 2.3, .2], [-.3, 2.9, .2], [.3, 2.9, .2]])
    faces = np.array([[0, 1, 2], [2, 1, 3]])
    # Two distant UV islands must not be interpreted as distant regions of the face.
    uv = np.array([[.05, .05], [.45, .05], [.05, .95], [.45, .95]])
    normals = np.tile([0, 0, 1.], (4, 1))
    projector = TextureProjector(UVBaker(faces, uv, 64), faces, uv)
    rng = np.random.default_rng(12)
    old = rng.uniform(.2, .8, (64, 64, 3))
    new = np.roll(old, 2, axis=1)
    projection = write_face_transition(projector, vertices, normals, old, new, 2.25, tmp_path)
    assert projection[2] > .6
    assert json.loads(json.dumps(projection)) == projection
    for direction, portrait in (("forward", "previous"), ("backward", "next")):
        flow = np.asarray(Image.open(tmp_path / f"flow_{direction}.png"))
        alpha = np.asarray(Image.open(tmp_path / f"portrait_{portrait}.png"))[..., 3]
        assert flow.shape == (256, 256, 3)
        assert np.all(flow[alpha == 0, 2] == 0)
        assert np.any(flow[alpha > 0, 2] > 100)
