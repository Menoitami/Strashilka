"""Validate two actual consecutive live packets, including morph/material continuity."""

import argparse
import json
import struct
from pathlib import Path

import numpy as np


def read_glb(path):
    raw = path.read_bytes()
    length = struct.unpack_from("<I", raw, 12)[0]
    document = json.loads(raw[20 : 20 + length])
    binary = memoryview(raw)[28 + length :]

    def array(index):
        accessor = document["accessors"][index]
        view = document["bufferViews"][accessor["bufferView"]]
        dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[accessor["componentType"]]
        components = {"VEC2": 2, "VEC3": 3, "VEC4": 4, "SCALAR": 1}[accessor["type"]]
        return np.frombuffer(
            binary,
            dtype=dtype,
            count=accessor["count"] * components,
            offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        ).reshape(-1, components)

    return document["meshes"][0]["primitives"][0], array


def verify(directory):
    packets = sorted(Path(directory).glob("frame_*/forms.json"))
    if len(packets) < 2:
        raise ValueError("Need two completed live packets")
    left, right = (p.parent for p in packets[-2:])
    old, old_array = read_glb(left / "creature.glb")
    new, new_array = read_glb(right / "creature.glb")
    previous = json.loads((left / "forms.json").read_text())
    current = json.loads((right / "forms.json").read_text())
    assert previous["sequence"] + 1 == current["sequence"]
    assert previous["seed"] != current["seed"]
    assert previous["diffusion"]["mock"] is False and current["reconstruction"]["neural"] is True
    for attribute in ["POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"]:
        np.testing.assert_array_equal(
            old_array(old["attributes"][attribute]), new_array(new["attributes"][attribute])
        )
    for attribute in ["POSITION", "NORMAL"]:
        np.testing.assert_allclose(
            old_array(old["targets"][1][attribute]), new_array(new["targets"][0][attribute]), atol=1e-6
        )
    for channel in ["albedo", "normal"]:
        assert (left / f"next_{channel}.png").read_bytes() == (right / f"previous_{channel}.png").read_bytes()
        assert (left / f"next_{channel}.png").read_bytes() != (right / f"next_{channel}.png").read_bytes()
    delta = new_array(new["targets"][1]["POSITION"]) - new_array(new["targets"][0]["POSITION"])
    movement = np.linalg.norm(delta, axis=1)
    np.testing.assert_allclose(movement.mean(), current["mean_change_m"], atol=1e-6)
    if "shape_step_m" in current:
        assert movement.max() <= current["shape_step_m"] + 1e-5
        assert current["conditioning"] == "previous_concept_and_previous_mesh"
        if current["shape_step_m"] > 0:
            assert movement.max() > 1e-6
    else:
        assert current["mean_change_m"] > 0.01
    print(
        f"LIVE CONTINUITY PASSED: #{previous['sequence']} -> #{current['sequence']}, identical endpoints and bind data; new seed, shape, color and normals"
    )
    return right


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    verify(parser.parse_args().directory)
