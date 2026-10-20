"""Portable skinned glTF 2.0 + Unity payload; all numeric buffers are little-endian."""

import json
import struct
from pathlib import Path

import numpy as np

from .rigging import humanoid_rig, walk_channels, weights_for_vertices


class GLB:
    def __init__(self):
        self.binary = bytearray()
        self.document = {
            "asset": {"version": "2.0", "generator": "SpookyNeuro neural 3D prototype"},
            "bufferViews": [],
            "accessors": [],
        }

    def accessor(self, data, kind, component=5126, bounds=False, target=None):
        dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[component]
        array = np.asarray(data, dtype=dtype)
        padding = -len(self.binary) % 4
        self.binary.extend(b"\0" * padding)
        offset = len(self.binary)
        self.binary.extend(array.tobytes())
        view = len(self.document["bufferViews"])
        self.document["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": array.nbytes})
        if target is not None:
            self.document["bufferViews"][-1]["target"] = target
        accessor = {"bufferView": view, "componentType": component, "count": len(array), "type": kind}
        if bounds:
            accessor.update(
                min=array.reshape(len(array), -1).min(0).tolist(),
                max=array.reshape(len(array), -1).max(0).tolist(),
            )
        self.document["accessors"].append(accessor)
        return len(self.document["accessors"]) - 1

    def save(self, path):
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        self.document["buffers"] = [{"byteLength": len(self.binary)}]
        metadata = json.dumps(self.document, separators=(",", ":"), allow_nan=False).encode()
        metadata += b" " * (-len(metadata) % 4)
        size = 12 + 8 + len(metadata) + 8 + len(self.binary)
        Path(path).write_bytes(
            struct.pack("<4sII", b"glTF", 2, size)
            + struct.pack("<I4s", len(metadata), b"JSON")
            + metadata
            + struct.pack("<I4s", len(self.binary), b"BIN\0")
            + self.binary
        )


def density_morph(mesh, density, metadata):
    """Bounded iso-density displacement; no remeshing, so joints/indices stay valid."""
    from scipy.ndimage import map_coordinates
    from scipy.sparse import coo_matrix

    vertices = np.asarray(mesh.vertices)
    radius = metadata["field_radius"]
    scale = metadata["field_scale"]
    raw_yup = vertices / scale + metadata["field_center_yup"]
    raw = raw_yup[:, [2, 0, 1]]
    coords = ((raw + radius) / (2 * radius) * (density.shape[0] - 1)).T
    log_density = np.log(np.maximum(density, 1e-7))
    field_gradients = np.gradient(log_density, 2 * radius / (density.shape[0] - 1))
    gradient = np.column_stack([map_coordinates(g, coords, order=1, mode="nearest") for g in field_gradients])
    displacement = gradient * (0.45 / (np.sum(gradient**2, axis=1, keepdims=True) + 1e-5))
    displacement = displacement[:, [1, 2, 0]] * scale
    lengths = np.linalg.norm(displacement, axis=1, keepdims=True)
    displacement *= np.minimum(1, 0.055 / np.maximum(lengths, 1e-8))
    edges = mesh.edges_unique
    rows = np.concatenate([edges[:, 0], edges[:, 1]])
    columns = np.concatenate([edges[:, 1], edges[:, 0]])
    adjacency = coo_matrix((np.ones(len(rows)), (rows, columns)), shape=(len(vertices),) * 2).tocsr()
    degree = np.maximum(1, np.asarray(adjacency.sum(1)).ravel())
    for _ in range(3):
        displacement = 0.5 * displacement + 0.5 * (adjacency @ displacement) / degree[:, None]
    # Smaller motion at narrow limb joints; the field should not collapse thin fingers.
    displacement *= np.clip(vertices[:, 1:2] / 0.2, 0, 1)
    # Bound per-triangle distortion: halve until no triangle flips or collapses.
    faces = np.asarray(mesh.faces)
    baseline = np.cross(
        vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]]
    )
    for _ in range(12):
        altered = vertices + displacement
        changed = np.cross(
            altered[faces[:, 1]] - altered[faces[:, 0]], altered[faces[:, 2]] - altered[faces[:, 0]]
        )
        good = np.sum(baseline * changed, axis=1) > 0.15 * np.sum(baseline**2, axis=1)
        if good.all():
            break
        affected = np.unique(faces[~good])
        displacement[affected] *= 0.5
    return displacement.astype(np.float32)


def smooth_normals(vertices, faces):
    """Preserve smooth lighting across duplicate vertices at UV atlas seams."""
    import trimesh

    welded, inverse = np.unique(vertices, axis=0, return_inverse=True)
    normals = np.array(trimesh.Trimesh(welded, inverse[faces], process=False).vertex_normals)
    valid = np.linalg.norm(normals, axis=1) > 1e-6
    if not valid.all():
        # Sub-millimetre slivers may collapse after float32 export. Supply a valid
        # adjacent normal instead of exporting zero-length lighting vectors.
        from scipy.spatial import cKDTree

        if valid.any():
            closest = cKDTree(welded[valid]).query(welded[~valid])[1]
            normals[~valid] = normals[valid][closest]
        else:
            normals[:] = [0, 1, 0]
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8)
    return normals[inverse]


def export_creature(
    mesh,
    output,
    metadata,
    morph=None,
    joint_override=None,
    morph_targets=None,
    uvs=None,
    tangents=None,
    legacy_payload=True,
):
    import trimesh

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    colors = np.asarray(mesh.visual.vertex_colors, dtype=np.float32) / 255
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    if uvs is not None:
        normals = smooth_normals(vertices, faces).astype(np.float32)
    names, parents, positions = humanoid_rig()
    if joint_override:
        override = json.loads(Path(joint_override).read_text())
        if [j["name"] for j in override] != names or [j["parent"] for j in override] != parents.tolist():
            raise ValueError(
                "Joint override must retain the humanoid's 19 names, order and parents; edit positions only"
            )
        names = [j["name"] for j in override]
        parents = np.array([j["parent"] for j in override], dtype=np.int32)
        positions = np.array([j["position"] for j in override], dtype=np.float32)
        if positions.shape != (19, 3) or not np.isfinite(positions).all():
            raise ValueError("Joint positions must contain 19 finite XYZ coordinates")
        if any(parent >= i or parent < -1 for i, parent in enumerate(parents)):
            raise ValueError("Joints must be parent-first")
    indices, weights = weights_for_vertices(vertices, parents, positions)
    if morph is None:
        morph = np.zeros_like(vertices)
    changed = trimesh.Trimesh(vertices + morph, faces, process=False)
    delta_normals = (changed.vertex_normals - normals).astype(np.float32)
    exporter = GLB()
    attrs = {
        key: exporter.accessor(value, kind, component, bounds=key == "POSITION", target=34962)
        for key, value, kind, component in [
            ("POSITION", vertices, "VEC3", 5126),
            ("NORMAL", normals, "VEC3", 5126),
            ("COLOR_0", colors, "VEC4", 5126),
            ("JOINTS_0", indices, "VEC4", 5123),
            ("WEIGHTS_0", weights, "VEC4", 5126),
        ]
    }
    primitive = {
        "attributes": attrs,
        "indices": exporter.accessor(faces.reshape(-1), "SCALAR", 5125, target=34963),
        "material": 0,
        "targets": [
            {
                "POSITION": exporter.accessor(morph, "VEC3", bounds=True, target=34962),
                "NORMAL": exporter.accessor(delta_normals, "VEC3", target=34962),
            }
        ],
    }
    target_names = ["DensityShift"]
    if uvs is not None:
        attrs["TEXCOORD_0"] = exporter.accessor(uvs, "VEC2", target=34962)
    if tangents is not None:
        attrs["TANGENT"] = exporter.accessor(tangents, "VEC4", target=34962)
    if morph_targets is not None:
        primitive["targets"] = []
        target_names = []
        for name, delta in morph_targets:
            target_names.append(name)
            target_mesh = trimesh.Trimesh(vertices + delta, faces, process=False)
            primitive["targets"].append(
                {
                    "POSITION": exporter.accessor(delta, "VEC3", bounds=True, target=34962),
                    "NORMAL": exporter.accessor(
                        (
                            smooth_normals(vertices + delta, faces)
                            if uvs is not None
                            else target_mesh.vertex_normals
                        )
                        - normals,
                        "VEC3",
                        target=34962,
                    ),
                }
            )
    doc = exporter.document
    doc["materials"] = [
        {
            "name": "Neural vertex color",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorFactor": [1, 1, 1, 1],
                "metallicFactor": 0,
                "roughnessFactor": 0.83,
            },
        }
    ]
    doc["meshes"] = [
        {
            "name": "NeuralCreature",
            "primitives": [primitive],
            "weights": [0] * len(target_names),
            "extras": {"targetNames": target_names},
        }
    ]
    doc["nodes"] = [
        {"name": "NeuralCreature", "children": [2]},
        {"name": "NeuralSurface", "mesh": 0, "skin": 0},
    ]
    for i, name in enumerate(names):
        parent = parents[i]
        translation = positions[i] - (positions[parent] if parent >= 0 else 0)
        node = {"name": name, "translation": translation.tolist()}
        children = (np.flatnonzero(parents == i) + 2).tolist()
        if children:
            node["children"] = children
        doc["nodes"].append(node)
    inverse = np.tile(np.eye(4, dtype=np.float32), (len(names), 1, 1))
    inverse[:, :3, 3] = -positions
    doc["skins"] = [
        {
            "name": "Humanoid19",
            "skeleton": 2,
            "joints": list(range(2, len(names) + 2)),
            "inverseBindMatrices": exporter.accessor(inverse.transpose(0, 2, 1).reshape(-1, 16), "MAT4"),
        }
    ]
    doc.update(scene=0, scenes=[{"nodes": [0, 1]}])
    times, channels = walk_channels(names, positions)
    time_accessor = exporter.accessor(times, "SCALAR", bounds=True)
    animation = {"name": "CreepWalk", "samplers": [], "channels": []}
    for bone, path, values in channels:
        sampler = len(animation["samplers"])
        output_accessor = exporter.accessor(values, "VEC4" if path == "rotation" else "VEC3")
        animation["samplers"].append(
            {"input": time_accessor, "output": output_accessor, "interpolation": "LINEAR"}
        )
        animation["channels"].append({"sampler": sampler, "target": {"node": bone + 2, "path": path}})
    doc["animations"] = [animation]
    exporter.save(output / "creature.glb")
    if not legacy_payload:
        return metadata
    # A dependency-free Unity importer can consume this identical geometry and rig.
    payload = {
        "schema": 1,
        "vertices": vertices.reshape(-1).tolist(),
        "normals": normals.reshape(-1).tolist(),
        "triangles": faces.reshape(-1).tolist(),
        "colors": colors.reshape(-1).tolist(),
        "boneNames": names,
        "parents": parents.tolist(),
        "joints": positions.reshape(-1).tolist(),
        "boneIndices": indices.reshape(-1).tolist(),
        "weights": weights.reshape(-1).tolist(),
        "morph": morph.reshape(-1).tolist(),
        "morphNormals": delta_normals.reshape(-1).tolist(),
    }
    (output / "creature.spooky.json").write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    (output / "joints.json").write_text(
        json.dumps(
            [
                {"name": name, "parent": int(parents[i]), "position": positions[i].tolist()}
                for i, name in enumerate(names)
            ],
            indent=2,
        )
    )
    metadata = dict(
        metadata,
        joints=len(names),
        skinned=True,
        animation="CreepWalk",
        morph="bounded neural iso-density shift",
        morph_max_m=float(np.linalg.norm(morph, axis=1).max()),
    )
    (output / "generation.json").write_text(json.dumps(metadata, indent=2))
    return metadata
