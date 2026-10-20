"""Register neural reconstructions to one skin, bake shared UV maps, export morphs."""

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.sparse import coo_matrix, eye
from scipy.sparse.linalg import factorized
from scipy.spatial import cKDTree

from .rigging import humanoid_rig, weights_for_vertices


def regions(vertices):
    _, parents, joints = humanoid_rig()
    ids, weights = weights_for_vertices(vertices, parents, joints)
    dominant = ids[np.arange(len(ids)), weights.argmax(1)]
    groups = np.zeros(len(vertices), dtype=np.int32)
    groups[np.asarray(vertices)[:, 1] > 2.23] = 1
    for low, high, group in [(5, 7, 2), (8, 10, 3), (11, 14, 4), (15, 18, 5)]:
        groups[(dominant >= low) & (dominant <= high)] = group
    return groups


def adjacency(mesh):
    edges = mesh.edges_unique
    rows = np.r_[edges[:, 0], edges[:, 1]]
    cols = np.r_[edges[:, 1], edges[:, 0]]
    matrix = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(mesh.vertices),) * 2).tocsr()
    return matrix


def register_surface(base, target, iterations=12):
    """Anatomy-gated nearest-surface fitting with a smooth displacement field.

    Both inputs are actual neural meshes in the same A-pose. This transfers their
    proportions onto the original indices; it cannot add or remove limbs.
    """
    vertices = np.asarray(base.vertices)
    target_vertices = np.asarray(target.vertices)
    group, target_group = regions(vertices), regions(target_vertices)
    matrix = adjacency(base)
    degree = np.asarray(matrix.sum(1)).ravel()
    laplacian = coo_matrix((degree, (np.arange(len(degree)),) * 2), shape=matrix.shape).tocsr() - matrix
    smooth = factorized((eye(len(vertices), format="csc") + 2.5 * laplacian).tocsc())
    current = vertices.copy()
    trees = {}
    for g in np.unique(group):
        selected = np.flatnonzero(target_group == g)
        if not len(selected):
            raise ValueError(f"Reconstruction is missing anatomical region {g}")
        trees[g] = (selected, cKDTree(target_vertices[selected]))
        source_mask = group == g
        original = vertices[source_mask]
        destination = target_vertices[selected]
        src_center = np.median(original, axis=0)
        dst_center = np.median(destination, axis=0)
        extent = np.maximum(np.quantile(original, 0.95, axis=0) - np.quantile(original, 0.05, axis=0), 0.05)
        target_extent = np.quantile(destination, 0.95, axis=0) - np.quantile(destination, 0.05, axis=0)
        scale = np.clip(target_extent / extent, 0.55, 1.8)
        # Keep longitudinal joint locations stable; change girth more than limb length.
        scale[1] = np.clip(scale[1], 0.85, 1.15)
        offset = np.clip(dst_center - src_center, -0.12, 0.12)
        current[source_mask] = (original - src_center) * scale + src_center + offset
    current = vertices + np.column_stack([smooth((current - vertices)[:, axis]) for axis in range(3)])
    for _ in range(iterations):
        goal = current.copy()
        for g, (selected, tree) in trees.items():
            mask = group == g
            distance, index = tree.query(current[mask], k=min(4, len(selected)))
            if distance.ndim == 1:
                distance, index = distance[:, None], index[:, None]
            weights = 1 / (distance + 0.015) ** 2
            weights /= weights.sum(1, keepdims=True)
            goal[mask] = np.sum(target_vertices[selected[index]] * weights[..., None], axis=1)
        displacement = (current - vertices) * 0.45 + (goal - vertices) * 0.55
        displacement = np.column_stack([smooth(displacement[:, axis]) for axis in range(3)])
        lengths = np.linalg.norm(displacement, axis=1, keepdims=True)
        displacement *= np.minimum(1, 0.65 / np.maximum(lengths, 1e-7))
        current = vertices + displacement
    return current.astype(np.float32)


def sample_surface(mesh, points):
    """Sample color and geometry normals from the reconstructed target, region by region."""
    groups, target_groups = regions(points), regions(mesh.vertices)
    colors = np.empty((len(points), 3), dtype=np.float32)
    normals = np.empty_like(colors)
    for g in np.unique(groups):
        selection = np.flatnonzero(target_groups == g)
        if not len(selection):
            selection = np.arange(len(mesh.vertices))
        mask = groups == g
        distance, index = cKDTree(np.asarray(mesh.vertices)[selection]).query(
            points[mask], k=min(4, len(selection))
        )
        if distance.ndim == 1:
            distance, index = distance[:, None], index[:, None]
        weight = 1 / (distance + 0.003) ** 2
        weight /= weight.sum(1, keepdims=True)
        chosen = selection[index]
        colors[mask] = (np.asarray(mesh.visual.vertex_colors)[chosen, :3] / 255 * weight[..., None]).sum(1)
        normals[mask] = (np.asarray(mesh.vertex_normals)[chosen] * weight[..., None]).sum(1)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8)
    return colors, normals


def tangent_frame(vertices, faces, uvs, normals):
    tri = vertices[faces]
    uv = uvs[faces]
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    det = np.where(np.abs(det) < 1e-10, 1e-10, det)
    ft = (e1 * d2[:, 1, None] - e2 * d1[:, 1, None]) / det[:, None]
    fb = (e2 * d1[:, 0, None] - e1 * d2[:, 0, None]) / det[:, None]
    tangent = np.zeros_like(vertices, dtype=np.float64)
    bitangent = np.zeros_like(tangent)
    for corner in range(3):
        np.add.at(tangent, faces[:, corner], ft)
        np.add.at(bitangent, faces[:, corner], fb)
    tangent -= normals * np.sum(tangent * normals, axis=1, keepdims=True)
    missing = np.linalg.norm(tangent, axis=1) < 1e-8
    if missing.any():
        # Degenerate UV islands still need an orthonormal tangent for valid glTF.
        basis = np.eye(3)[np.abs(normals[missing]).argmin(axis=1)]
        tangent[missing] = np.cross(basis, normals[missing])
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-8)
    cross = np.cross(normals, tangent)
    sign = np.where(np.sum(cross * bitangent, axis=1) < 0, -1.0, 1.0)
    return tangent, cross * sign[:, None], sign


def bake_maps(faces, uvs, colors, normal_vectors, output, size=1024):
    """Rasterize a shared UV atlas and dilate gutters. UV v=0 maps to top in glTF."""
    canvas = np.zeros((size, size, 6), dtype=np.float32)
    covered = np.zeros((size, size), dtype=bool)
    pixels = uvs * (size - 1)
    values = np.concatenate([colors, normal_vectors], axis=1)
    for face in faces:
        p = pixels[face]
        low = np.maximum(0, np.floor(p.min(0)).astype(int))
        high = np.minimum(size - 1, np.ceil(p.max(0)).astype(int))
        xx, yy = np.meshgrid(np.arange(low[0], high[0] + 1), np.arange(low[1], high[1] + 1))
        a, b, c = p
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-9:
            continue
        w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
        w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
        w2 = 1 - w0 - w1
        valid = (w0 >= -0.001) & (w1 >= -0.001) & (w2 >= -0.001)
        blended = (
            w0[..., None] * values[face[0]]
            + w1[..., None] * values[face[1]]
            + w2[..., None] * values[face[2]]
        )
        canvas[yy[valid], xx[valid]] = blended[valid]
        covered[yy[valid], xx[valid]] = True
    if not covered.any():
        raise ValueError("UV atlas has no covered pixels")
    nearest = distance_transform_edt(~covered, return_distances=False, return_indices=True)
    canvas[~covered] = canvas[nearest[0][~covered], nearest[1][~covered]]
    normals = canvas[..., 3:]
    normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1e-7)
    Image.fromarray((np.clip(canvas[..., :3], 0, 1) * 255).astype(np.uint8)).save(str(output) + "_albedo.png")
    Image.fromarray((np.clip(normals * 0.5 + 0.5, 0, 1) * 255).astype(np.uint8)).save(
        str(output) + "_normal.png"
    )
    return float(covered.mean())


class UVBaker:
    """Cache rasterization once, then bake each live neural surface with vector operations."""

    def __init__(self, faces, uvs, size=512):
        self.size = size
        self.indices = np.zeros((size, size, 3), dtype=np.int32)
        self.weights = np.zeros((size, size, 3), dtype=np.float32)
        covered = np.zeros((size, size), dtype=bool)
        pixels = uvs * (size - 1)
        for face in faces:
            p = pixels[face]
            low = np.maximum(0, np.floor(p.min(0)).astype(int))
            high = np.minimum(size - 1, np.ceil(p.max(0)).astype(int))
            xx, yy = np.meshgrid(np.arange(low[0], high[0] + 1), np.arange(low[1], high[1] + 1))
            a, b, c = p
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denominator) < 1e-9:
                continue
            w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
            w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
            weights = np.stack([w0, w1, 1 - w0 - w1], axis=-1)
            valid = (weights >= -0.001).all(-1)
            self.indices[yy[valid], xx[valid]] = face
            self.weights[yy[valid], xx[valid]] = weights[valid]
            covered[yy[valid], xx[valid]] = True
        if not covered.any():
            raise ValueError("Empty atlas")
        nearest = distance_transform_edt(~covered, return_distances=False, return_indices=True)
        for array in [self.indices, self.weights]:
            array[~covered] = array[nearest[0][~covered], nearest[1][~covered]]

    def bake(self, colors, normals, path):
        values = np.concatenate([colors, normals], axis=1)
        canvas = (values[self.indices] * self.weights[..., None]).sum(2)
        normal = canvas[..., 3:]
        normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-7)
        Image.fromarray((np.clip(canvas[..., :3], 0, 1) * 255).astype(np.uint8)).save(
            str(path) + "_albedo.png"
        )
        Image.fromarray((np.clip(normal * 0.5 + 0.5, 0, 1) * 255).astype(np.uint8)).save(
            str(path) + "_normal.png"
        )
