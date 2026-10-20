import json

from PIL import Image, ImageDraw

from spookyneuro.dataset import allowed_license, prepare


def test_license_filter():
    assert allowed_license("CC BY-SA 4.0")
    assert allowed_license("Public domain")
    assert not allowed_license("CC BY-NC 4.0")
    assert not allowed_license("Fair use")


def test_duplicate_removed_before_split(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    records = []
    for i in range(4):
        im = Image.new("RGB", (400, 400), "black")
        draw = ImageDraw.Draw(im)
        draw.rectangle((30 + i * 70, 40, 100 + i * 70, 300), fill="white")
        im.save(root / f"{i}.png")
        records.append(
            {"file": f"{i}.png", "page_id": i, "sha256": str(i), "class": "human", "caption": "human"}
        )
    # Identical image with a different name must not leak into validation.
    (root / "copy.png").write_bytes((root / "0.png").read_bytes())
    records.append(dict(records[0], file="copy.png", page_id=42))
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    out = tmp_path / "prepared"
    prepare(root, out)
    prepared = [json.loads(line) for line in (out / "manifest.jsonl").read_text().splitlines()]
    assert len(prepared) <= 4
    assert not any(r["page_id"] == 42 for r in prepared)
    assert all((out / r["prepared_file"]).exists() for r in prepared)
    assert {r["split"] for r in prepared} == {"train", "validation"}
