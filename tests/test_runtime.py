import os
import subprocess
import sys

import pytest

from spookyneuro.runtime import godot_command, gpu_job, process_exists


def test_gpu_lease_blocks_concurrent_models_and_releases_after_error(tmp_path):
    path = tmp_path / "gpu.lock"
    with pytest.raises(ValueError), gpu_job(path=path):
        with pytest.raises(RuntimeError, match="Another SpookyNeuro"), gpu_job(path=path):
            pass
        raise ValueError("Job failed")
    with gpu_job(path=path):
        pass


def test_parent_probe_does_not_terminate_a_live_process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_exists(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert not process_exists(child.pid)
    assert not process_exists(0)


def test_exported_player_works_from_a_path_with_spaces(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOOKY_GAME", raising=False)
    root = tmp_path / "Creature Lab"
    root.mkdir()
    player = root / "SpookyNeuro.exe"
    player.touch()
    assert godot_command(root) == [str(player)]
    player.unlink()
    executable = "godot.exe" if os.name == "nt" else "godot"
    assert godot_command(root) == [str(root / ".tools" / executable), "--path", str(root / "godot")]
