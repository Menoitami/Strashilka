"""A window must never open on partial, mock or failed first inference."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "launch_3d", Path(__file__).resolve().parents[1] / "scripts/launch_3d.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def packet(directory):
    folder = directory / "frame_000001"
    folder.mkdir()
    for name in launcher.REQUIRED_PACKET_FILES:
        (folder / name).write_bytes(b"complete")
    data = {
        "sequence": 1, "directory": str(folder),
        "diffusion": {"mock": False}, "reconstruction": {"neural": True},
        "texture_method": "projection",
        "texture": {name: {"diffusion": {"mock": False}} for name in ("front", "back", "face")},
    }
    (directory / "latest.json").write_text(json.dumps(data))
    return data


def test_wait_accepts_only_complete_neural_packet(tmp_path):
    expected = packet(tmp_path)
    (Path(expected["directory"]) / "next_normal.png").unlink()
    assert launcher.ready_packet(tmp_path) is None
    (Path(expected["directory"]) / "next_normal.png").write_bytes(b"complete")
    worker = Mock()
    worker.poll.return_value = None
    assert launcher.wait_ready(worker, tmp_path) == expected


@pytest.mark.parametrize("component", ["geometry", "face"])
def test_mock_results_do_not_start_game(tmp_path, component):
    data = packet(tmp_path)
    if component == "geometry":
        data["diffusion"]["mock"] = True
    else:
        data["texture"]["face"]["diffusion"]["mock"] = True
    (tmp_path / "latest.json").write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="not a real neural"):
        launcher.ready_packet(tmp_path)


def test_dead_worker_is_failure_even_with_published_packet(tmp_path):
    packet(tmp_path)
    worker = Mock()
    worker.poll.return_value = 1
    (tmp_path / "status.json").write_text(json.dumps({"error": "CUDA failure"}))
    with pytest.raises(RuntimeError, match="CUDA failure"):
        launcher.wait_ready(worker, tmp_path)


def test_incomplete_packet_times_out(tmp_path, monkeypatch):
    worker = Mock()
    worker.poll.return_value = None
    times = iter([0, 601])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError):
        launcher.wait_ready(worker, tmp_path)


def test_first_packet_must_belong_to_current_session(tmp_path):
    data = packet(tmp_path)
    data["directory"] = str(tmp_path.parent / "old_session/frame_000001")
    (tmp_path / "latest.json").write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="outside its session"):
        launcher.ready_packet(tmp_path)
