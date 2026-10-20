"""Conservative humanoid skinning; shared topology is retained for animation.

This is an explicit A-pose prior, not a learned universal autorigger. Joint locations
may be overridden with a JSON list of {name,parent,position} in model coordinates.
"""

import numpy as np


def humanoid_rig():
    names = ["Pelvis", "Spine", "Chest", "Neck", "Head"]
    parents = [-1, 0, 1, 2, 3]
    positions = [[0, 1.02, 0], [0, 1.38, 0], [0, 1.92, 0], [0, 2.24, 0], [0, 2.56, 0]]
    for sign, side in [(-1, "L"), (1, "R")]:
        start = len(names)
        names += [f"Shoulder{side}", f"Elbow{side}", f"Wrist{side}"]
        parents += [2, start, start + 1]
        # Same A-pose as the exported anatomical guide (shoulder rotation .48 rad).
        positions += [[sign * 0.43, 1.98, 0], [sign * 0.88, 1.58, 0.02], [sign * 1.16, 1.12, 0.1]]
    for sign, side in [(-1, "L"), (1, "R")]:
        start = len(names)
        names += [f"Hip{side}", f"Knee{side}", f"Ankle{side}", f"Toe{side}"]
        parents += [0, start, start + 1, start + 2]
        positions += [
            [sign * 0.22, 1.03, 0],
            [sign * 0.25, 0.56, 0.015],
            [sign * 0.26, 0.12, 0.02],
            [sign * 0.26, 0.07, 0.25],
        ]
    return names, np.array(parents, dtype=np.int32), np.array(positions, dtype=np.float32)


def weights_for_vertices(vertices, parents, joints):
    """Four segment influences, with anatomical gates to avoid arm-to-rib welding."""
    vertices = np.asarray(vertices)
    distances = []
    for i, origin in enumerate(joints):
        children = np.flatnonzero(parents == i)
        end = joints[children[0]] if len(children) else origin + [0, 0.12, 0]
        if i in (7, 10):  # A-pose hand segments continue down and outward from each wrist.
            end = origin + [(-1 if origin[0] < 0 else 1) * 0.14, -0.28, 0.04]
        if i == 2:  # Chest has shoulder children: keep its central torso influence vertical.
            end = joints[3]
        if i == 0:
            end = joints[1]
        segment = end - origin
        t = np.clip(((vertices - origin) * segment).sum(1) / (np.dot(segment, segment) + 1e-8), 0, 1)
        distance = np.linalg.norm(vertices - origin - t[:, None] * segment, axis=1)
        distances.append(distance)
    distances = np.array(distances).T
    x, y = vertices[:, 0], vertices[:, 1]
    # Gates follow the chosen skeleton, including the longer-legged realistic body.
    hip_height = joints[11, 1]
    shoulder_height = joints[5, 1]
    arm_boundary = abs(joints[5, 0]) + .15
    for i in range(len(joints)):
        # Arm and leg segments should never attract opposite-side surface vertices.
        if i >= 5:
            side = -1 if joints[i, 0] < 0 else 1
            distances[x * side < -0.03, i] += 4
        if 5 <= i <= 10:
            # A-pose fingers can sit below the hips; horizontal separation identifies
            # them as hands. A height-only gate incorrectly bound them to the legs.
            distances[(y < hip_height-.13) & (np.abs(x) < arm_boundary+.07), i] += 3
            distances[np.abs(x) < abs(joints[5, 0])*.7, i] += 1
        if i >= 11:
            distances[y > hip_height+.22, i] += 3
            distances[np.abs(x) > arm_boundary+.07, i] += 3
        if i < 5:
            distances[(np.abs(x) > arm_boundary) & (y < shoulder_height+.14), i] += 2
            distances[y < hip_height-.25, i] += 2
    indices = np.argsort(distances, axis=1)[:, :4]
    selected = np.take_along_axis(distances, indices, axis=1)
    # Narrow falloff limits stretchy webs. Normalized and finite even at joints.
    weights = np.exp(-(selected - selected[:, 0, None]) / 0.075)
    weights /= weights.sum(axis=1, keepdims=True)
    return indices.astype(np.uint16), weights.astype(np.float32)


def rotation_quaternion(axis, radians):
    result = np.zeros((*np.asarray(radians).shape, 4), dtype=np.float32)
    result[..., axis] = np.sin(np.asarray(radians) / 2)
    result[..., 3] = np.cos(np.asarray(radians) / 2)
    return result


def walk_channels(names, positions, duration=2.4, samples=49):
    """Looping rotations plus pelvis bob; no bone scaling or detached limb meshes."""
    times = np.linspace(0, duration, samples, dtype=np.float32)
    phase = times / duration * 2 * np.pi
    channels = []
    for i, name in enumerate(names):
        axis, angle = 0, None
        if name == "Chest":
            angle = 0.12 + 0.045 * np.sin(2 * phase)
        elif name == "Head":
            axis = 2
            angle = 0.09 + 0.07 * np.sin(phase) + 0.16 * np.maximum(0, np.sin(2 * phase)) ** 20
        elif name.startswith("Hip"):
            angle = 0.34 * np.sin(phase + (np.pi if name.endswith("L") else 0))
        elif name.startswith("Knee"):
            stride = np.sin(phase + (np.pi if name.endswith("L") else 0))
            angle = -0.06 - 0.45 * np.maximum(0, -stride)
        elif name.startswith("Ankle"):
            angle = 0.09 * np.sin(phase + (np.pi if name.endswith("L") else 0))
        elif name.startswith("Shoulder"):
            angle = -0.22 * np.sin(phase + (np.pi if name.endswith("L") else 0))
        elif name.startswith("Elbow"):
            angle = -0.10 + 0.09 * np.sin(phase + (np.pi if name.endswith("L") else 0))
        if angle is not None:
            if name.endswith("L"):
                angle = angle * 0.72
            channels.append((i, "rotation", rotation_quaternion(axis, angle)))
    bob = np.tile(positions[0], (samples, 1))
    bob[:, 1] += 0.018 * np.sin(2 * phase)
    channels.append((0, "translation", bob.astype(np.float32)))
    return times, channels


def skin_vertices(vertices, joint_indices, weights, parents, positions, rotations):
    """CPU linear blend skinning reference for verification/export previews."""
    from scipy.spatial.transform import Rotation

    matrices = []
    for i, parent in enumerate(parents):
        local = np.eye(4)
        local[:3, :3] = Rotation.from_quat(rotations[i]).as_matrix()
        local[:3, 3] = positions[i] - (positions[parent] if parent >= 0 else 0)
        matrices.append(matrices[parent] @ local if parent >= 0 else local)
    transforms = np.array(matrices)
    transforms[:, :3, 3] -= np.einsum("nij,nj->ni", transforms[:, :3, :3], positions)
    homogeneous = np.column_stack([vertices, np.ones(len(vertices))])
    transformed = np.einsum("nkij,nj->nki", transforms[joint_indices], homogeneous)[..., :3]
    return (transformed * weights[..., None]).sum(1)
