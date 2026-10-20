"""Check foreground occlusion and return-to-view consistency in rendered captures."""
import argparse
import json

import cv2
import numpy as np
from PIL import Image


def verify(directory):
    def read(name):
        return np.asarray(Image.open(directory / (name+".png"))).astype("int16")
    before, after = read("occlusion_off"), read("occlusion_on")
    mask = ((before[..., 1]>180)&(before[..., 0]<25)&(before[..., 2]<25)).astype("uint8")
    # Exclude the rasterized silhouette edge; verify the entire foreground interior.
    mask = cv2.erode(mask, np.ones((3, 3), dtype="uint8")).astype(bool)
    difference = np.max(np.abs(before-after), axis=-1)
    result = {
        "foreground_pixels": int(mask.sum()),
        "foreground_max_difference": int(difference[mask].max()) if mask.any() else -1,
        "changed_background_pixels": int((difference[~mask]>0).sum()),
        "full_orbit_max_difference": int(np.max(np.abs(read("orbit_00")-read("orbit_08")))),
    }
    (directory / "checks.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    assert result["foreground_pixels"] > 1000
    assert result["foreground_max_difference"] == 0
    assert result["changed_background_pixels"] > 0
    assert result["full_orbit_max_difference"] <= 1


if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
