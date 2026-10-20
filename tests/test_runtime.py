import pytest

from spookyneuro.runtime import gpu_job


def test_gpu_lease_blocks_concurrent_models_and_releases_after_error(tmp_path):
    path = tmp_path / "gpu.lock"
    with pytest.raises(ValueError), gpu_job(path=path):
        with pytest.raises(RuntimeError, match="Another SpookyNeuro"), gpu_job(path=path):
            pass
        raise ValueError("Job failed")
    with gpu_job(path=path):
        pass
