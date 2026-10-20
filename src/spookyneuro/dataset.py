"""Small, resumable Commons collector with attribution and duplicate-safe splits."""

import hashlib
import html
import io
import json
import logging
import re
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageOps

LOG = logging.getLogger(__name__)
API = "https://commons.wikimedia.org/w/api.php"
SEARCHES = {
    "human": [
        "portrait photograph -intitle:MET -intitle:painting",
        '"full body" person -intitle:MET',
        "human face photograph",
    ],
    "animal": ["animal mammal portrait", "wolf head", "deer full body", "reptile head"],
    "monster": [
        "monster sculpture",
        "gargoyle statue",
        "grotesque sculpture",
        "monster mask",
        "mythological creature",
    ],
}


def clean(value):
    return html.unescape(re.sub(r"<[^>]*>", " ", value or "")).strip()


def allowed_license(name):
    name = name.lower().strip()
    return name in ("cc0", "cc0 1.0", "public domain", "pd") or bool(
        re.fullmatch(r"cc by(?:-sa)? \d\.\d(?: [a-z-]+)?", name)
    )


def is_artwork(categories):
    return bool(
        re.search(
            r"paintings|engravings|drawings|lithographs|illustrations|sculptures|statues|prints|watercolors|sketches",
            categories,
            re.IGNORECASE,
        )
    )


def collect(output, per_class=250, delay=1.0):
    if per_class < 1 or delay < 0.1:
        raise ValueError("Use a positive class size and request delay >= 0.1 s")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.jsonl"
    records = [json.loads(line) for line in manifest.read_text().splitlines()] if manifest.exists() else []
    seen = {r["page_id"] for r in records}
    digests = {r["sha256"] for r in records}
    excluded_path = root / "exclude.txt"
    excluded = set(excluded_path.read_text().split()) if excluded_path.exists() else set()
    session = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session.mount(
        "https://",
        HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])),
    )
    session.headers["User-Agent"] = "SpookyNeuroResearch/0.1 (local noncommercial art experiment; requests)"
    for label, searches in SEARCHES.items():
        count = sum(r["class"] == label and str(r["page_id"]) not in excluded for r in records)
        folder = root / label
        folder.mkdir(exist_ok=True)
        for query in searches:
            continuation = {}
            while count < per_class:
                params = dict(
                    action="query",
                    format="json",
                    generator="search",
                    gsrsearch=query + " filetype:bitmap",
                    gsrnamespace=6,
                    gsrlimit=50,
                    prop="imageinfo",
                    iiprop="url|extmetadata|size",
                    iiurlwidth=960,
                    **continuation,
                )
                time.sleep(delay)
                response = session.get(API, params=params, timeout=45)
                response.raise_for_status()
                payload = response.json()
                if "error" in payload:
                    raise RuntimeError(payload["error"])
                pages = payload.get("query", {}).get("pages", {})
                for page in pages.values():
                    if count >= per_class:
                        break
                    if page["pageid"] in seen:
                        continue
                    info = page.get("imageinfo", [{}])[0]
                    ext = info.get("extmetadata", {})
                    get = lambda key, ext=ext: clean(ext.get(key, {}).get("value", ""))
                    license_name = get("LicenseShortName")
                    if (
                        not allowed_license(license_name)
                        or min(info.get("width", 0), info.get("height", 0)) < 384
                    ):
                        continue
                    title = page["title"]
                    if not re.search(r"\.(jpe?g|png|webp)$", title, re.IGNORECASE):
                        continue
                    categories = get("Categories")
                    if label in ("human", "animal") and is_artwork(categories):
                        continue
                    if re.search(r"watermark|logo|collage|diagram|map of|coat of arms", title, re.IGNORECASE):
                        continue
                    url = info.get("thumburl", info.get("url", ""))
                    if "thumbnail_unscaled" in url:
                        continue
                    if not url or not re.search(r"\.(jpe?g|png|webp)(?:$|\?)", url, re.IGNORECASE):
                        continue
                    try:
                        time.sleep(delay)
                        download = session.get(url, timeout=(8, 30))
                        if download.status_code == 429:
                            LOG.warning("Rate limited; pausing downloads for 60 seconds")
                            time.sleep(max(60, int(download.headers.get("Retry-After", "60"))))
                            continue
                        download.raise_for_status()
                        with Image.open(io.BytesIO(download.content)) as opened:
                            image = ImageOps.exif_transpose(opened).convert("RGB")
                        digest = hashlib.sha256(image.tobytes()).hexdigest()
                        if digest in digests:
                            continue
                        filename = f"{label}/{page['pageid']}.jpg"
                        image.save(root / filename, quality=94)
                        caption_title = re.sub(r"\.[^.]+$", "", title.removeprefix("File:"))
                        record = dict(
                            file=filename,
                            page_id=page["pageid"],
                            title=title,
                            **{
                                "class": label,
                                "sha256": digest,
                                "source": info.get("descriptionurl"),
                                "download_url": url,
                                "author": get("Artist"),
                                "license": license_name,
                                "license_url": get("LicenseUrl"),
                                "attribution": get("Attribution"),
                                "categories": categories,
                                "caption": f"spookycreature, {label}, {caption_title}",
                            },
                        )
                        with manifest.open("a") as f:
                            f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        records.append(record)
                        seen.add(page["pageid"])
                        digests.add(digest)
                        count += 1
                        if count % 10 == 0:
                            LOG.info("Collected %s: %d/%d", label, count, per_class)
                    except (requests.RequestException, OSError, ValueError) as exc:
                        LOG.warning("Skipping %s: %s", title, exc)
                if "continue" not in payload:
                    break
                continuation = payload["continue"]
        LOG.info("Finished %s: %d/%d", label, count, per_class)
    contact_sheets(root, records)
    return records


def perceptual_hash(image):
    # dHash, with near-duplicate grouping before assigning train/validation.
    gray = np.array(image.convert("L").resize((9, 8)))
    bits = gray[:, 1:] > gray[:, :-1]
    return int.from_bytes(np.packbits(bits).tobytes(), "big")


def contact_sheets(root, records):
    exclude_path = root / "exclude.txt"
    excluded = set(exclude_path.read_text().split()) if exclude_path.exists() else set()
    for label in SEARCHES:
        subset = [r for r in records if r["class"] == label and str(r["page_id"]) not in excluded]
        for offset in range(0, len(subset), 80):
            canvas = Image.new("RGB", (1000, 1000), (25, 25, 25))
            draw = ImageDraw.Draw(canvas)
            for index, record in enumerate(subset[offset : offset + 80]):
                with Image.open(root / record["file"]) as image:
                    thumb = ImageOps.contain(image.convert("RGB"), (96, 104))
                x, y = index % 10 * 100, index // 10 * 125
                canvas.paste(thumb, (x, y))
                draw.text((x, y + 105), str(record["page_id"]), fill="white")
            canvas.save(root / f"contact_{label}_{offset // 80:02d}.jpg")


def prepare(source, output):
    root, out = Path(source), Path(output)
    records = [json.loads(line) for line in (root / "manifest.jsonl").read_text().splitlines()]
    exclusions = root / "exclude.txt"
    excluded = set(exclusions.read_text().split()) if exclusions.exists() else set()
    selected, hashes = [], []
    for record in records:
        if str(record["page_id"]) in excluded:
            continue
        if not re.search(r"\.(jpe?g|png|webp)$", record.get("title", record["file"]), re.IGNORECASE):
            continue
        with Image.open(root / record["file"]) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            if min(image.size) < 256 or max(image.size) / min(image.size) > 3:
                continue
            phash = perceptual_hash(image)
            if any((phash ^ old).bit_count() <= 6 for old in hashes):
                continue
            hashes.append(phash)
        selected.append(record)
    out.mkdir(parents=True, exist_ok=True)
    # Split deterministically per class after deduplication (at least one holdout/class).
    for label in SEARCHES:
        subset = sorted((r for r in selected if r["class"] == label), key=lambda r: r["sha256"])
        validation_count = max(1, round(len(subset) * 0.1))
        for i, record in enumerate(subset):
            split = "validation" if i < validation_count else "train"
            record["split"] = split
            target = out / split
            target.mkdir(exist_ok=True)
            filename = f"{record['page_id']}.jpg"
            with Image.open(root / record["file"]) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                # Letterboxing retains limbs; neutral background instead of destructive center crop.
                square = ImageOps.pad(image, (512, 512), color=(8, 8, 8))
                square.save(target / filename, quality=95)
            record["prepared_file"] = f"{split}/{filename}"
    (out / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected))
    summary = {split: sum(r["split"] == split for r in selected) for split in ("train", "validation")}
    summary["classes"] = {
        label: {
            split: sum(r["class"] == label and r["split"] == split for r in selected)
            for split in ("train", "validation")
        }
        for label in SEARCHES
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    LOG.info("Prepared: %s", summary)
