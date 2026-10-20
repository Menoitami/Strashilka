"""Summarize a completed scene run and its renderer log without guessing FPS."""

import argparse
import json
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--game", default="artifacts/soak.json")
parser.add_argument("--server", default="artifacts/server.jsonl")
parser.add_argument("--output", default="artifacts/soak-summary.json")
args = parser.parse_args()
game = json.loads(Path(args.game).read_text())
records = [json.loads(line) for line in Path(args.server).read_text().splitlines()]
# Dedicated soak logs are preferable; append-only shared logs may contain earlier runs.
if records:
    # A new game resets capture timestamps and request IDs.
    starts = [i for i, r in enumerate(records) if i == 0 or r["id"] <= records[i - 1]["id"]]
    records = records[starts[-1] :]
summary = {"game": game, "server_frames": len(records)}
for key in (
    "render_ms",
    "segmentation_ms",
    "flow_ms",
    "server_ms",
    "allocated_vram_mib",
    "reserved_vram_mib",
):
    values = [r[key] for r in records if key in r]
    if values:
        summary[key] = {
            "median": float(np.median(values)),
            "p95": float(np.percentile(values, 95)),
            "first": values[0],
            "last": values[-1],
            "max": max(values),
        }
summary["dropped_max"] = max((r.get("dropped", 0) for r in records), default=0)
Path(args.output).write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
