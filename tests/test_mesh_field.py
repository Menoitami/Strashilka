import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")
from spookyneuro.mesh_export import density_morph


def test_neural_field_morph_preserves_topology_and_triangle_orientation():
    # Analytic density fixture checks extraction math without pretending to run a model.
    axis = np.linspace(-1, 1, 40)
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    density = np.exp((0.5 - np.sqrt(x * x + y * y + z * z)) * 12) * 25
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
    mesh.vertices += [0, 1, 0]
    stats = {"field_radius": 1.0, "field_scale": 1.0, "field_center_yup": [0, -1, 0]}
    delta = density_morph(mesh, density, stats)
    assert np.isfinite(delta).all()
    assert 0.001 < np.linalg.norm(delta, axis=1).max() <= 0.0551
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    changed = vertices + delta
    normal = np.cross(
        vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]]
    )
    new_normal = np.cross(
        changed[faces[:, 1]] - changed[faces[:, 0]], changed[faces[:, 2]] - changed[faces[:, 0]]
    )
    assert np.all(np.sum(normal * new_normal, axis=1) > 0)
    # Increasing iso-density should move into the sphere, not inflate it.
    assert np.mean(np.sum(delta * (vertices - [0, 1, 0]), axis=1)) < 0
