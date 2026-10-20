"""One diffusion/training job per user, to avoid competing for an 8 GB GPU."""

import getpass
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import psutil

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def process_exists(pid):
    """Probe without os.kill(pid, 0), which can terminate a process on Windows."""
    return pid > 0 and psutil.pid_exists(pid)


def godot_command(root):
    """Use the exported player when packaged, otherwise the local editor."""
    root = Path(root)
    override = os.environ.get("SPOOKY_GAME")
    player = Path(override) if override else root / "SpookyNeuro.exe"
    if override or player.is_file():
        return [str(player)]
    executable = root / ".tools" / ("godot.exe" if os.name == "nt" else "godot")
    return [str(executable), "--path", str(root / "godot")]


@contextmanager
def gpu_job(enabled=True, path=None):
    if not enabled:
        yield
        return
    user = getpass.getuser() if os.name == "nt" else str(os.getuid())
    lock_path = Path(path) if path else Path(tempfile.gettempdir()) / f"spookyneuro-{user}-gpu.lock"
    with lock_path.open("a+b") as lock:
        if lock_path.stat().st_size == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "Another SpookyNeuro GPU job is running; stop it before loading another model."
            ) from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
