import importlib.util
import json
import os
import threading
import time
from pathlib import Path

import pytest


def launcher():
    path = Path(__file__).resolve().parents[1]/"scripts/launch_3d.py"
    spec = importlib.util.spec_from_file_location("field_launcher",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_queue(root, count):
    packets = []
    for sequence in range(1,count+1):
        folder = root/f"field_{sequence:06d}"
        folder.mkdir(exist_ok=True)
        packet = {"schema":2,"sequence":sequence,"directory":str(folder),"resolution":64,
                  "bytes":64**3*4,"diffusion":{"mock":False},"reconstruction":{"neural":True}}
        (folder/"field.json").write_text(json.dumps(packet))
        (folder/"field.rgba").write_bytes(bytes(packet["bytes"]))
        packets.append({"sequence":sequence,"directory":str(folder)})
    (root/"latest.json").write_text(json.dumps(packet))
    (root/"queue.json").write_text(json.dumps({"schema":1,"capacity":3,"packets":packets}))


def test_start_waits_for_prefill_and_plays_first_not_latest(tmp_path):
    module = launcher()
    seed_queue(tmp_path,2)
    assert module.ready_packet(tmp_path) is None
    seed_queue(tmp_path,3)
    assert module.ready_packet(tmp_path)["sequence"] == 1
    (tmp_path/"field_000003/field.rgba").write_bytes(b"truncated")
    assert module.ready_packet(tmp_path) is None


def test_prefill_rejects_foreign_directory_and_mock_future_state(tmp_path):
    module = launcher()
    seed_queue(tmp_path,3)
    path = tmp_path/"field_000003/field.json"
    packet = json.loads(path.read_text())
    packet["diffusion"]["mock"] = True
    path.write_text(json.dumps(packet))
    with pytest.raises(RuntimeError,match="not a real neural"):
        module.ready_packet(tmp_path)
    queue = json.loads((tmp_path/"queue.json").read_text())
    queue["packets"][2]["directory"] = str(tmp_path.parent/"other-session")
    (tmp_path/"queue.json").write_text(json.dumps(queue))
    with pytest.raises(RuntimeError,match="outside"):
        module.ready_packet(tmp_path)


@pytest.mark.skipif(os.name != "nt",reason="Windows file-sharing regression")
def test_atomic_publication_survives_a_windows_reader(tmp_path):
    path = Path(__file__).resolve().parents[1]/"scripts/live_3d.py"
    spec = importlib.util.spec_from_file_location("field_writer",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path/"status.json"
    target.write_text('{"old":true}')
    errors = []
    def publish():
        try:
            module.atomic_json(target,{"new":True})
        except OSError as error:
            errors.append(error)
    with target.open("rb"):
        thread = threading.Thread(target=publish)
        thread.start()
        time.sleep(.08)
        assert json.loads(target.read_text()) == {"old":True}
    thread.join(timeout=2)
    assert not thread.is_alive() and not errors
    assert json.loads(target.read_text()) == {"new":True}
