import json
import logging
import queue
import socket
import threading
import time
from pathlib import Path

from .imaging import flow_fields, png_bytes, read_png
from .protocol import encode_message, receive_message

LOG = logging.getLogger(__name__)


def serve(renderer, host="127.0.0.1", port=7861, log_path="artifacts/server.jsonl"):
    """One client at a time; receiver keeps only the newest waiting request."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with socket.create_server((host, port), backlog=1) as listener:
        LOG.info("Listening on %s:%d (mock=%s)", host, port, renderer.mock)
        while True:
            conn, address = listener.accept()
            LOG.info("Connected: %s", address)
            with conn:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                _client(conn, renderer, log_path)


def _client(conn, renderer, log_path):
    waiting = queue.Queue(maxsize=1)
    stopped = threading.Event()
    dropped = [0]

    def receive():
        try:
            while not stopped.is_set():
                request = receive_message(conn)
                if waiting.full():
                    try:
                        waiting.get_nowait()
                        dropped[0] += 1
                    except queue.Empty:
                        pass
                waiting.put_nowait(request)
        except (EOFError, OSError, ValueError):
            stopped.set()

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    previous = None
    previous_id = None
    previous_epoch = None
    try:
        with open(log_path, "a", buffering=1) as log:
            while not stopped.is_set():
                try:
                    meta, blobs = waiting.get(timeout=0.2)
                except queue.Empty:
                    continue
                started = time.perf_counter()
                try:
                    epoch = meta.get("epoch", 0)
                    if epoch != previous_epoch:
                        previous, previous_id = None, None
                    image, metrics = renderer.render(read_png(blobs["image"]), meta)
                    result = {"image": png_bytes(image)}
                    flow_start = time.perf_counter()
                    if (
                        previous is not None
                        and meta.get("interpolation", renderer.settings.interpolation) == "flow"
                    ):
                        fwd, backward = flow_fields(previous, image)
                        result["forward"] = fwd.tobytes()
                        result["backward"] = backward.tobytes()
                    metrics["flow_ms"] = (time.perf_counter() - flow_start) * 1000
                    metrics["server_ms"] = (time.perf_counter() - started) * 1000
                    metrics["dropped"] = dropped[0]
                    response = dict(
                        metrics,
                        id=meta["id"],
                        epoch=epoch,
                        previous_id=previous_id,
                        captured_ms=meta.get("captured_ms"),
                        size=image.width,
                    )
                    conn.sendall(encode_message(response, result))
                    log.write(json.dumps(response) + "\n")
                    previous, previous_id, previous_epoch = image, meta["id"], epoch
                except (BrokenPipeError, ConnectionResetError):
                    break
                except Exception as exc:
                    LOG.exception("Request failed")
                    conn.sendall(encode_message({"id": meta.get("id"), "error": str(exc)}, {}))
    except (OSError, EOFError):
        pass
    finally:
        stopped.set()
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        thread.join(timeout=2)
