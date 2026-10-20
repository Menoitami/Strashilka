"""One diffusion/training job per user, to avoid competing for an 8 GB GPU."""

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def gpu_job(enabled=True, path=None):
    if not enabled:
        yield
        return
    lock_path = Path(path) if path else Path(tempfile.gettempdir()) / f"spookyneuro-{os.getuid()}-gpu.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Another SpookyNeuro GPU job is running; stop it before loading another model."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
