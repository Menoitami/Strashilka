"""Reviewed synthetic subset; preserve rejected teacher samples for audit, never train on them."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "data/body-horror"
out = root / "data/body-horror-curated"
out.mkdir(exist_ok=True)
# Visually reviewed on contact sheets: omit cartoons, faceless blobs, ordinary
# portraits, embedded text, missing torsos and infant-like proportions.
descriptions = {
    4: "gaunt torso, sinewy arms, distorted open mouth",
    5: "elongated jaw, stretched neck tendons, exposed rib contours",
    8: "asymmetric elongated head and stretched chest tendons",
    13: "sunken face and knotted chest muscles",
    16: "long neck and asymmetric muscular shoulders",
    19: "elongated face, thin torso and twisted long fingers",
    20: "loose folds of skin and swollen uneven arms",
    22: "contracted neck and asymmetric muscular torso",
    24: "swollen hunched shoulders and compressed torso",
    25: "uneven shoulders, thin arms and mottled skin",
    26: "stretched mouth merging with neck tendons, long sinewy arms",
    28: "strained jaw, taut ribbed chest and elongated fingers",
    29: "gaunt distorted face, sunken torso and contorted hands",
    32: "long neck and twisted muscular shoulders",
    34: "stretched sinewy torso and bony elbows",
    37: "pale skin, uneven musculature and crooked fingers",
    43: "raised bony shoulder ridges and elongated neck",
    44: "stretched neck tendons and long knotted torso",
    45: "swollen muscular chest and head tilted backward",
    51: "distorted skull with sunken eyes, sinewy ribbed chest and arms",
    56: "misshapen jaw, sunken abdomen and knotted arm muscles",
    59: "distorted face, asymmetric shoulders and long fingers",
    61: "stretched open mouth, elongated arms and contorted fingers",
}
held_out = {8, 22, 34, 59}
records = []
for i, description in descriptions.items():
    original_split = "validation" if i % 8 == 7 else "train"
    relative = f"{original_split}/{81000 + i}.png"
    dest = out / relative
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        dest.symlink_to(source / relative)
    records.append(
        {
            "prepared_file": relative,
            "split": "validation" if i in held_out else "train",
            "class": "monster",
            "caption": "anatomyhorror, full body humanoid horror creature, "
            + description
            + ", pale flesh, practical prosthetic monster, black background",
            "source": "synthetic SD1.5 img2img, manually selected and recaptioned",
            "seed": 81000 + i,
        }
    )
(out / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
(out / "curation.json").write_text(
    json.dumps(
        {
            "synthetic": True,
            "teacher_candidates": 64,
            "retained": len(records),
            "training": len(records) - len(held_out),
            "held_out": len(held_out),
            "excluded": [81000 + i for i in range(64) if i not in descriptions],
            "limits": "Small anatomy/style pilot, not a diverse production body-horror dataset. TripoSR is unchanged.",
        },
        indent=2,
    )
)
print(f"{len(records) - len(held_out)} training, {len(held_out)} held out")
