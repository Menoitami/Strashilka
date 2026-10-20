import socket
import struct
import threading

import pytest

from spookyneuro.protocol import encode_message, receive_message


def test_fragmented_frames_and_back_to_back_messages():
    a, b = socket.socketpair()
    wire = encode_message({"id": 4}, {"image": b"png", "flow": b"float"}) + encode_message({"id": 5}, {})

    def send():
        with a:
            for byte in wire:
                a.sendall(bytes([byte]))

    thread = threading.Thread(target=send)
    thread.start()
    with b:
        assert receive_message(b) == ({"id": 4}, {"image": b"png", "flow": b"float"})
        assert receive_message(b) == ({"id": 5}, {})
        with pytest.raises(EOFError):
            receive_message(b)
    thread.join()


@pytest.mark.parametrize(
    "wire",
    [struct.pack("!I", 70000), struct.pack("!I", 0), encode_message({}, {})[:4] + b'{"blobs":{"x":-1}}'],
)
def test_bad_lengths_rejected(wire):
    a, b = socket.socketpair()
    with a, b:
        a.sendall(wire)
        a.shutdown(socket.SHUT_WR)
        with pytest.raises((ValueError, EOFError)):
            receive_message(b)
