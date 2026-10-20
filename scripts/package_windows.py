"""Export Godot and package the Windows player with the neural worker/bootstrap."""

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/windows/SpookyNeuro-Windows-x86_64"


def package():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for args in (
        ["--headless", "--path", str(ROOT / "godot"), "--editor", "--import", "--quit"],
        ["--headless", "--path", str(ROOT / "godot"), "--export-release", "Windows Desktop",
         str(OUTPUT / "SpookyNeuro.exe")],
    ):
        subprocess.run([str(ROOT / ".tools/godot.exe"), *args], cwd=ROOT, check=True)
    files = [
        ROOT / name for name in (
            "pyproject.toml", "uv.lock", "README.md", "THREE_D.md", "INSTALL_WINDOWS_RU.txt",
            "Start SpookyNeuro.cmd", "Offline Preview.cmd", "Mutation Demo.cmd", "Neural Entity Demo.cmd", ".tools/uv.exe",
        )
    ]
    for folder in (
        "src", "configs", "third_party", "assets", "docs",
        "artifacts/3d/generated", "artifacts/body-horror-lora", ".tools/TripoSR/tsr",
    ):
        files.extend(
            path for path in (ROOT / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    files.extend(
        path for path in (ROOT / "scripts").glob("*.py")
        if not path.name.startswith("package_")
    )
    files.extend(ROOT / "scripts" / name for name in ("setup_windows.ps1", "run_windows.ps1"))
    files.extend((ROOT / "artifacts/3d").glob("guide*.png"))
    for path in files:
        destination = OUTPUT / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    manifest = {}
    with zipfile.ZipFile(OUTPUT.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        # An existing local test environment must never leak into the release.
        packaged = {OUTPUT / path.relative_to(ROOT) for path in files}
        packaged.update(OUTPUT / name for name in ("SpookyNeuro.exe", "SpookyNeuro.pck"))
        console = OUTPUT / "SpookyNeuro.console.exe"
        if console.exists():
            packaged.add(console)
        for path in sorted(packaged):
            relative = path.relative_to(OUTPUT).as_posix()
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest[relative] = {"bytes": path.stat().st_size, "sha256": digest}
            archive.write(path, OUTPUT.name + "/" + relative)
        archive.writestr(OUTPUT.name + "/PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2))
    release = OUTPUT.with_suffix(".zip")
    with zipfile.ZipFile(release) as archive:
        if bad := archive.testzip():
            raise RuntimeError("ZIP CRC failed: " + bad)
    with release.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    release.with_suffix(".zip.sha256").write_text(f"{digest}  {release.name}\n", encoding="utf-8")
    print(f"Built {release} ({release.stat().st_size / 2**20:.1f} MiB), {len(manifest)} files")


if __name__ == "__main__":
    package()
