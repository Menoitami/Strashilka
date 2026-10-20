"""Build the Linux (Arch) source release with runtime seeds and installation guide."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".godot", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_FILES = {
    "scripts/package_windows.py", "godot/export_presets.cfg", "docs/WINDOWS_VALIDATION_RU.md",
}
ROOT_FILES = [
    ".gitignore", "pyproject.toml", "uv.lock", "README.md", "THREE_D.md", "RESULTS.md",
    "INSTALL_ARCH_RU.txt",
]
RUNTIME_ASSETS = [
    "artifacts/3d/generated/creature.glb",
    "artifacts/3d/generated/creature.spooky.json",
    "artifacts/3d/generated/unrigged.ply",
    "artifacts/3d/generated/joints.json",
    "artifacts/3d/guide.png",
    "artifacts/3d/guide_swollen.png",
    "artifacts/3d/guide_chitin.png",
    "artifacts/body-horror-lora/lora/pytorch_lora_weights.safetensors",
    "artifacts/body-horror-lora/approved.json",
    "artifacts/body-horror-lora/training.json",
]


def package():
    files = {ROOT / name for name in ROOT_FILES + RUNTIME_ASSETS}
    for folder in ("src", "scripts", "godot", "configs", "tests", "third_party", "unity", "assets", "docs"):
        files.update(
            path for path in (ROOT / folder).rglob("*")
            if path.is_file() and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
            and path.suffix not in {".pyc", ".ps1", ".cmd", ".exe"}
            and path.relative_to(ROOT).as_posix() not in EXCLUDED_FILES
            and not {"Library", "Temp", "Logs", "Obj", "Generated"}.intersection(path.relative_to(ROOT).parts)
        )
    output = ROOT / "dist/linux/SpookyNeuro-Arch-x86_64.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            if path.is_symlink():
                raise RuntimeError(f"Release must not depend on symlinks: {path}")
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            # Linux archives must remain runnable when packaged on Windows.
            executable = path.suffix == ".sh"
            if executable:
                data = data.replace(b"\r\n", b"\n")
            manifest[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            info = zipfile.ZipInfo.from_file(path, "SpookyNeuro/" + relative)
            info.create_system = 3
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        archive.writestr(
            "SpookyNeuro/PACKAGE_MANIFEST.json",
            json.dumps({"format": 1, "files": manifest}, ensure_ascii=False, indent=2) + "\n",
        )
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("ZIP CRC failed: " + bad)
        for relative, info in manifest.items():
            data = archive.read("SpookyNeuro/" + relative)
            if len(data) != info["bytes"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise RuntimeError("ZIP manifest mismatch: " + relative)
        for script in ("setup.sh", "setup_3d.sh", "run.sh", "run_3d.sh", "check.sh"):
            if not (archive.getinfo("SpookyNeuro/scripts/" + script).external_attr >> 16) & 0o111:
                raise RuntimeError("Missing executable permission: " + script)
            if b"\r\n" in archive.read("SpookyNeuro/scripts/" + script):
                raise RuntimeError("Linux script contains CRLF: " + script)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    print(f"{output}\n{len(manifest)} files + manifest, {output.stat().st_size / 2**20:.2f} MiB\n{digest}")


if __name__ == "__main__":
    package()
