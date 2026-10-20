"""Animation/export invariants, independent of downloading or running a neural model."""

import json
import struct

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")
from spookyneuro.mesh_export import export_creature
from spookyneuro.rigging import humanoid_rig, skin_vertices, walk_channels, weights_for_vertices


def test_skin_rest_identity_and_local_limb_influence():
    names, parents, positions = humanoid_rig()
    points = np.array(
        [[0, 2.7, 0], [-1.18, 1.1, 0.12], [1.18, 1.1, 0.12], [-0.25, 0.4, 0.04], [0.25, 0.4, 0.04]],
        dtype=np.float32,
    )
    indices, weights = weights_for_vertices(points, parents, positions)
    assert np.all(np.isfinite(weights))
    np.testing.assert_allclose(weights.sum(1), 1, atol=1e-6)
    rest = np.tile([0.0, 0.0, 0.0, 1.0], (len(names), 1))
    np.testing.assert_allclose(
        skin_vertices(points, indices, weights, parents, positions, rest), points, atol=1e-6
    )
    rotated = rest.copy()
    angle = 0.4
    rotated[names.index("ElbowL")] = [np.sin(angle / 2), 0, 0, np.cos(angle / 2)]
    moved = skin_vertices(points, indices, weights, parents, positions, rotated)
    assert np.linalg.norm(moved[1] - points[1]) > 0.05
    assert np.linalg.norm(moved[2] - points[2]) < 0.001
    assert np.linalg.norm(moved[4] - points[4]) < 0.001


def test_walk_loop_and_hierarchy():
    names, parents, positions = humanoid_rig()
    assert len(names) == 19
    assert all(parent < i for i, parent in enumerate(parents))
    times, channels = walk_channels(names, positions)
    assert np.all(np.diff(times) > 0)
    for bone, path, values in channels:
        np.testing.assert_allclose(values[0], values[-1], atol=1e-6)
        if path == "rotation":
            np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1, atol=1e-6)
    assert any(np.ptp(values[:, 0]) > 0.2 for bone, path, values in channels if path == "rotation")


def test_glb_skin_animation_round_trip_and_unity_payload(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.4)
    mesh.vertices += [0, 1.7, 0]
    mesh.visual.vertex_colors = np.tile([180, 120, 110, 255], (len(mesh.vertices), 1))
    morph = np.asarray(mesh.vertex_normals) * 0.008
    export_creature(mesh, tmp_path, {"neural": False, "test_fixture": True}, morph)
    content = (tmp_path / "creature.glb").read_bytes()
    magic, version, size = struct.unpack_from("<4sII", content)
    assert magic == b"glTF" and version == 2 and size == len(content)
    length, tag = struct.unpack_from("<I4s", content, 12)
    assert tag == b"JSON"
    document = json.loads(content[20 : 20 + length])
    assert len(document["skins"][0]["joints"]) == 19
    assert document["animations"][0]["name"] == "CreepWalk"
    assert document["meshes"][0]["extras"]["targetNames"] == ["DensityShift"]
    for view in document["bufferViews"]:
        assert view["byteOffset"] % 4 == 0
        assert view["byteOffset"] + view["byteLength"] <= document["buffers"][0]["byteLength"]
    loaded = trimesh.load(tmp_path / "creature.glb", force="scene")
    assert sum(len(geometry.vertices) for geometry in loaded.geometry.values()) == len(mesh.vertices)
    payload = json.loads((tmp_path / "creature.spooky.json").read_text())
    np.testing.assert_allclose(np.array(payload["weights"]).reshape(-1, 4).sum(1), 1, atol=1e-6)
    assert len(payload["morph"]) == len(payload["vertices"])
    assert max(payload["boneIndices"]) < 19
    assert max(payload["triangles"]) < len(mesh.vertices)


def test_low_a_pose_fingers_follow_wrists_instead_of_legs():
    names, parents, positions = humanoid_rig()
    points = np.array([[-1.35, 0.72, 0.1], [1.35, 0.72, 0.1]], dtype=np.float32)
    indices, weights = weights_for_vertices(points, parents, positions)
    assert names[indices[0, 0]] == "WristL"
    assert names[indices[1, 0]] == "WristR"
    for row in range(2):
        leg_weight = sum(w for index, w in zip(indices[row], weights[row], strict=True) if index >= 11)
        assert leg_weight < 0.001
