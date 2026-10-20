"""Populate every live-inference asset during setup; no CUDA allocation required."""

import argparse

from huggingface_hub import hf_hub_download
from huggingface_hub.errors import LocalEntryNotFoundError

from spookyneuro.model_assets import MODEL_FILES, MODEL_REVISIONS


def download(offline=False):
    for model, files in MODEL_FILES.items():
        for filename in files:
            args = {"repo_id": model, "filename": filename, "revision": MODEL_REVISIONS[model]}
            try:
                path = hf_hub_download(**args, local_files_only=True)
            except LocalEntryNotFoundError:
                if offline:
                    raise RuntimeError(
                        f"Missing cached asset: {model}/{filename}; run scripts/setup_3d.sh"
                    ) from None
                print(f"Downloading {model}/{filename}", flush=True)
                path = hf_hub_download(**args)
            print(f"OK {model}/{filename}", flush=True)
            if not path:
                raise RuntimeError("Empty asset path")
    print("All live models are cached; gameplay can run offline.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    download(parser.parse_args().offline)
