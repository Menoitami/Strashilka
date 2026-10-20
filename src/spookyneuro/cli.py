import argparse
import logging

from .config import Settings
from .runtime import gpu_job


def main():
    parser = argparse.ArgumentParser(description="SpookyNeuro experiment tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "benchmark"):
        p = sub.add_parser(name)
        p.add_argument("--config", default="configs/default.json")
        p.add_argument("--mock", action="store_true", help="Diagnostic warp, NOT a neural model")
        p.add_argument("--lora")
        p.add_argument("--size", type=int)
        p.add_argument("--steps", type=int, choices=(2, 4, 6, 8))
        p.add_argument("--strength", type=float)
        p.add_argument("--mask", choices=["fixed", "free"])
        p.add_argument("--mask-device", choices=["auto", "cpu", "cuda"])
        p.add_argument("--interpolation", choices=["flow", "blend"])
        if name == "serve":
            p.add_argument("--port", type=int, default=7861)
            p.add_argument("--log", default="artifacts/server.jsonl")
        else:
            p.add_argument("--output", default="artifacts/benchmark")
            p.add_argument("--frames", type=int, default=12)
            p.add_argument("--matrix", action="store_true")
            p.add_argument("--source", help="RGBA PNG from Godot or an existing test image")
    p = sub.add_parser("collect")
    p.add_argument("--output", default="data/commons")
    p.add_argument("--per-class", type=int, default=250)
    p.add_argument("--delay", type=float, default=1.0)
    p = sub.add_parser("prepare")
    p.add_argument("--source", default="data/commons")
    p.add_argument("--output", default="data/prepared")
    p = sub.add_parser("train")
    p.add_argument("--data", default="data/prepared")
    p.add_argument("--output", default="artifacts/horror-lora")
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--rank", type=int, default=8)
    p.add_argument("--size", type=int, choices=(256, 384, 512), default=512)
    p.add_argument("--resume", help="Full trainer checkpoint directory")
    p.add_argument("--batch-accumulation", type=int, default=1)
    p = sub.add_parser("generate-3d", help="Reconstruct a real skinned 3D mesh with pretrained TripoSR")
    p.add_argument("--source", default="artifacts/3d/concept_0.png")
    p.add_argument("--repository", default=".tools/TripoSR")
    p.add_argument("--output", default="artifacts/3d/generated")
    p.add_argument("--resolution", type=int, choices=(96, 128, 192, 256), default=192)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument("--joints", help="Optional parent-first A-pose joint JSON override")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    needs_gpu = (
        args.command == "train"
        or (args.command in ("serve", "benchmark") and not args.mock)
        or (args.command == "generate-3d" and args.device == "cuda")
    )
    with gpu_job(needs_gpu):
        execute(args, parser)


def execute(args, parser):
    if args.command in ("serve", "benchmark"):
        settings = Settings.load(args.config)
        for arg, key in [
            (args.lora, "lora"),
            (args.size, "size"),
            (args.mask, "mask_mode"),
            (args.mask_device, "mask_device"),
            (args.interpolation, "interpolation"),
            (args.steps, "steps"),
            (args.strength, "strength"),
        ]:
            if arg is not None:
                setattr(settings, key, arg)
        settings.validate()
        if args.command == "serve":
            from .renderer import Renderer
            from .server import serve

            serve(Renderer(settings, args.mock), port=args.port, log_path=args.log)
        else:
            if args.frames < 2:
                parser.error("--frames must be at least 2")
            from .benchmark import benchmark

            benchmark(settings, args.output, args.frames, args.mock, args.matrix, args.source)
    elif args.command == "collect":
        from .dataset import collect

        collect(args.output, args.per_class, args.delay)
    elif args.command == "prepare":
        from .dataset import prepare

        prepare(args.source, args.output)
    elif args.command == "generate-3d":
        import json
        from pathlib import Path

        from .mesh_export import density_morph, export_creature
        from .reconstruction import reconstruct

        mesh, density, image, stats = reconstruct(args.source, args.repository, args.resolution, args.device)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        image.save(output / "input.png")
        mesh.export(output / "unrigged.ply")
        morph = density_morph(mesh, density, stats)
        stats = export_creature(mesh, output, stats, morph, args.joints)
        print(json.dumps(stats, indent=2))
    else:
        from .training import train

        train(args)


if __name__ == "__main__":
    main()
