"""Wire format: big-endian u32 JSON length, JSON, then named binary blobs.

JSON contains `blobs`: ordered {name: byte_count}. All images are PNG RGBA;
flow fields are little-endian float32 H x W x 4 (dx, dy, confidence, 0).
Only listen on loopback; this is a local experimental protocol.
"""

import json
import socket
import struct

MAX_HEADER = 64 * 1024
MAX_BODY = 32 * 1024 * 1024


def receive_exact(sock: socket.socket, size: int) -> bytes:
    parts = bytearray()
    while len(parts) < size:
        chunk = sock.recv(size - len(parts))
        if not chunk:
            raise EOFError("Peer disconnected")
        parts.extend(chunk)
    return bytes(parts)


def encode_message(metadata: dict, blobs: dict[str, bytes]) -> bytes:
    header = dict(metadata, blobs={name: len(blob) for name, blob in blobs.items()})
    packed = json.dumps(header, allow_nan=False, separators=(",", ":")).encode()
    if len(packed) > MAX_HEADER or sum(map(len, blobs.values())) > MAX_BODY:
        raise ValueError("Message too large")
    return struct.pack("!I", len(packed)) + packed + b"".join(blobs.values())


def receive_message(sock: socket.socket) -> tuple[dict, dict[str, bytes]]:
    size = struct.unpack("!I", receive_exact(sock, 4))[0]
    if not 0 < size <= MAX_HEADER:
        raise ValueError("Invalid header length")
    header = json.loads(receive_exact(sock, size))
    if not isinstance(header, dict):
        raise ValueError("Header must be a JSON object")  # noqa: TRY004
    blobs = header.pop("blobs", {})
    if not isinstance(blobs, dict) or any(type(n) is not int or n < 0 for n in blobs.values()):
        raise ValueError("Invalid blob lengths")
    if sum(blobs.values()) > MAX_BODY:
        raise ValueError("Payload too large")
    return header, {key: receive_exact(sock, length) for key, length in blobs.items()}
