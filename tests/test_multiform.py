"""Shared topology and independently usable appearance maps are the morph contract."""

import json
import struct

import numpy as np
import pytest
from PIL import Image

trimesh = pytest.importorskip("trimesh")
from spookyneuro.mesh_export import export_creature
from spookyneuro.multiform import bake_maps, register_surface, tangent_frame


def test_registered_neural_surface_retains_indices_and_changes_volume():
    base = trimesh.creation.icosphere(subdivisions=3, radius=0.22)
    base.vertices += [0, 1.7, 0]
    target = base.copy()
    target.vertices = (target.vertices - [0, 1.7, 0]) * [1.7, 1, 1.6] + [0, 1.7, 0]
    registered = register_surface(base, target)
    assert registered.shape == base.vertices.shape
    assert np.isfinite(registered).all()
    assert np.ptp(registered[:, 0]) > np.ptp(base.vertices[:, 0]) * 1.25
    assert np.linalg.norm(registered - base.vertices, axis=1).mean() > 0.04
    # Registration to itself must not introduce a large unrelated deformation.
    identity = register_surface(base, base)
    assert np.linalg.norm(identity - base.vertices, axis=1).max() < 0.02


def test_uv_bake_color_and_normal_orientation_and_export(tmp_path):
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]])
    uv = vertices[:, :2]
    normals = np.tile([0, 0, 1.0], (3, 1))
    tangent, bitangent, sign = tangent_frame(vertices, faces, uv, normals)
    np.testing.assert_allclose(tangent, np.tile([1, 0, 0], (3, 1)))
    np.testing.assert_allclose(bitangent, np.tile([0, 1, 0], (3, 1)))
    colors = np.eye(3)
    coverage = bake_maps(faces, uv, colors, normals, tmp_path / "test", size=32)
    assert 0.45 < coverage < 0.6
    image = np.asarray(Image.open(tmp_path / "test_albedo.png"))
    np.testing.assert_array_equal(image[0, 31], [0, 255, 0])
    np.testing.assert_array_equal(image[31, 0], [0, 0, 255])
    normal_image = np.asarray(Image.open(tmp_path / "test_normal.png"))
    np.testing.assert_array_equal(normal_image[10, 10], [127, 127, 255])
    mesh = trimesh.Trimesh(vertices, faces, vertex_colors=np.full((3, 4), 255), process=False)
    export_creature(
        mesh,
        tmp_path,
        {},
        morph_targets=[("wide", vertices * 0.1), ("thin", -vertices * 0.1)],
        uvs=uv,
        tangents=np.column_stack([tangent, sign]),
    )
    data = (tmp_path / "creature.glb").read_bytes()
    size = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + size])
    primitive = doc["meshes"][0]["primitives"][0]
    assert len(primitive["targets"]) == 2
    assert doc["meshes"][0]["extras"]["targetNames"] == ["wide", "thin"]
    assert {"TEXCOORD_0", "TANGENT", "JOINTS_0", "WEIGHTS_0"} <= primitive["attributes"].keys()
    assert doc["meshes"][0]["weights"] == [0, 0]


def test_cached_baker_matches_reference_and_normals_cross_uv_seams(tmp_path):
    from spookyneuro.mesh_export import smooth_normals
    from spookyneuro.multiform import UVBaker

    faces = np.array([[0, 1, 2]])
    uv = np.array([[0.0, 0], [1, 0], [0, 1]])
    colors = np.eye(3)
    normals = np.tile([0, 0, 1.0], (3, 1))
    bake_maps(faces, uv, colors, normals, tmp_path / "reference", size=32)
    UVBaker(faces, uv, size=32).bake(colors, normals, tmp_path / "cached")
    for channel in ["albedo", "normal"]:
        expected = np.asarray(Image.open(tmp_path / f"reference_{channel}.png")).astype(int)
        actual = np.asarray(Image.open(tmp_path / f"cached_{channel}.png")).astype(int)
        assert np.max(np.abs(actual - expected)) <= 1
    # Shared geometric vertices split by a UV chart must retain the same smooth normal.
    vertices = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [0, 1, 0], [0, 0, 1]])
    smooth = smooth_normals(vertices, np.array([[0, 1, 2], [3, 4, 5]]))
    np.testing.assert_allclose(smooth[0], smooth[3])
    np.testing.assert_allclose(smooth[2], smooth[4])


def test_degenerate_uv_tangents_and_unreferenced_normals_are_unit_length():
    from spookyneuro.mesh_export import smooth_normals

    vertices = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0.01]])
    faces = np.array([[0, 1, 2]])
    normals = smooth_normals(vertices, faces)
    np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1)
    uv = np.zeros((4, 2))
    tangent, bitangent, _ = tangent_frame(vertices, faces, uv, normals)
    np.testing.assert_allclose(np.linalg.norm(tangent, axis=1), 1)
    np.testing.assert_allclose(np.linalg.norm(bitangent, axis=1), 1)
    np.testing.assert_allclose(np.sum(tangent * normals, axis=1), 0, atol=1e-6)
