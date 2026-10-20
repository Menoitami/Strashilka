import socket
import threading
from dataclasses import replace

import numpy as np
import pytest

from spookyneuro.config import Settings
from spookyneuro.imaging import flow_fields, interpolate, png_bytes, proxy_image, read_png
from spookyneuro.protocol import encode_message, receive_message
from spookyneuro.renderer import Renderer
from spookyneuro.server import _client


def test_fixed_alpha_and_interpolation_endpoints():
    source = proxy_image()
    renderer = Renderer(Settings(mask_mode="fixed"), mock=True)
    a, _ = renderer.render(source, {"phase": 0})
    b, _ = renderer.render(source, {"phase": 1})
    assert np.array_equal(np.array(a)[..., 3], np.array(source)[..., 3])
    fields = flow_fields(a, b)
    assert fields[0].shape == (256, 256, 4)
    assert np.isfinite(fields[0]).all()
    for t, expected in [(0, a), (1, b)]:
        result = np.array(interpolate(a, b, t, fields))
        expected = np.array(expected)
        visible = expected[..., 3] > 0
        assert np.abs(result.astype(int)[visible] - expected.astype(int)[visible]).max() <= 1
    mid = np.array(interpolate(a, b, 0.5, fields))
    assert mid[..., 3].max() == 255
    assert mid[0, 0, 3] == 0


def test_request_epoch_resets_flow_and_client_reconnect_cleanup(tmp_path):
    renderer = Renderer(Settings(mask_mode="fixed"), mock=True)
    server, client = socket.socketpair()
    thread = threading.Thread(target=_client, args=(server, renderer, str(tmp_path / "log.jsonl")))
    thread.start()
    with client:
        for index, epoch, expected_previous in [(1, 0, None), (2, 0, 1), (3, 1, None)]:
            client.sendall(
                encode_message(
                    {"id": index, "epoch": epoch, "phase": index}, {"image": png_bytes(proxy_image())}
                )
            )
            meta, blobs = receive_message(client)
            assert meta["previous_id"] == expected_previous
            assert meta["mock"] is True
            assert ("forward" in blobs) == (expected_previous is not None)
            assert read_png(blobs["image"]).size == (256, 256)
    thread.join(timeout=3)
    server.close()
    assert not thread.is_alive()


def test_render_error_does_not_kill_connection(tmp_path):
    server, client = socket.socketpair()
    thread = threading.Thread(target=_client, args=(server, Renderer(Settings(), True), str(tmp_path / "l")))
    thread.start()
    with client:
        client.sendall(encode_message({"id": 1}, {"image": b"bad png"}))
        assert "error" in receive_message(client)[0]
        client.sendall(encode_message({"id": 2}, {"image": png_bytes(proxy_image())}))
        assert receive_message(client)[0]["id"] == 2
    thread.join(timeout=3)
    server.close()
    assert not thread.is_alive()


@pytest.mark.parametrize("strength", [0.1, 0, 1.1])
def test_strength_requires_actual_steps(strength):
    with pytest.raises(ValueError):
        replace(Settings(), strength=strength).validate()


def test_generated_silhouette_can_extend_beyond_the_guide():
    source = proxy_image()
    result, _ = Renderer(Settings(mask_mode="free"), mock=True).render(source, {"phase": 1})
    old_alpha = np.array(source.getchannel("A"))
    new_alpha = np.array(result.getchannel("A"))
    assert ((new_alpha > 128) & (old_alpha == 0)).any()
    assert new_alpha[0, 0] == 0


def test_latent_walk_retains_variance_and_requested_temporal_correlation():
    from spookyneuro.renderer import correlate_noise

    rng = np.random.default_rng(55)
    previous, fresh = rng.normal(size=(2, 100000))
    result = correlate_noise(previous, fresh, 0.8)
    assert 0.98 < result.std() < 1.02
    assert 0.78 < np.corrcoef(previous, result)[0, 1] < 0.82
    np.testing.assert_array_equal(correlate_noise(previous, fresh, 0), fresh)
    np.testing.assert_array_equal(correlate_noise(previous[:2], fresh, 0.8), fresh)
