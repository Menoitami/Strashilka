import numpy as np
import pytest
from PIL import Image

from spookyneuro.neural_field import (
    change_focus,
    decode_density,
    encode_volume,
    feedback_image,
    field_alignment,
    front_projection,
    image_continuity,
    valid_silhouette,
    write_packet,
)


def test_density_codec_preserves_topology_and_color():
    density = np.zeros((64,)*3, dtype="float32")
    density[10:20, 12:25, 8:18] = 32
    density[40:45, 35:50, 41:53] = 60
    color = np.full((*density.shape, 3), [.3, .6, .9], dtype="float32")
    rgba = encode_volume(density, color)
    recovered = decode_density(rgba)
    assert np.array_equal(recovered>12, density>12)
    assert np.max(np.abs(recovered-density)) < 1
    assert np.max(np.abs(rgba[..., :3]/255-color)) <= 1/255
    alignment = field_alignment(rgba, .87)
    focus, amount = change_focus(rgba, rgba, alignment)
    assert amount == 0
    changed = rgba.copy()
    changed[40:45, 35:50, 41:53, 3] = 0
    focus, amount = change_focus(rgba, changed, alignment)
    assert amount > 0 and np.isfinite(focus).all()


def test_nonfinite_field_is_never_published(tmp_path):
    density = np.full((64,)*3, np.nan)
    with pytest.raises(ValueError, match="Non-finite"):
        encode_volume(density, np.zeros((*density.shape, 3)))
    rgba = np.zeros((64,64,64,4), dtype="uint8")
    manifest = write_packet(tmp_path, rgba, {"sequence": 1})
    assert manifest["bytes"] == (tmp_path / "field.rgba").stat().st_size == 64**3*4


def test_feedback_can_retain_a_generated_silhouette():
    anchor = Image.new("RGBA", (384,384), (0,0,0,0))
    previous = Image.new("RGBA", (384,384), (180,100,80,255))
    output = feedback_image(anchor, previous, 1)
    assert output.getpixel((0,0)) == (180,100,80,255)


def test_subject_loss_rejected_without_enforcing_human_anatomy():
    data = np.zeros((384,384,4), dtype="uint8")
    assert not valid_silhouette(Image.fromarray(data))
    data[30:350,160:220] = [120,100,90,255]
    data[180:200,45:300] = [120,100,90,255]
    data[75:95,80:340] = [120,100,90,255]
    assert valid_silhouette(Image.fromarray(data))
    data[:] = 255
    assert not valid_silhouette(Image.fromarray(data))


def test_adjacent_identity_gate_rejects_silhouette_and_color_jumps():
    data = np.zeros((128,128,4),dtype="uint8")
    data[10:118,35:90] = [160,120,95,255]
    image = Image.fromarray(data)
    neighbor = data.copy()
    neighbor[20:50,40:80,0] += 12
    assert image_continuity(image,Image.fromarray(neighbor))["accepted"]
    disjoint = np.zeros_like(data)
    disjoint[10:118,95:125] = [160,120,95,255]
    assert not image_continuity(image,Image.fromarray(disjoint))["accepted"]
    recolored = data.copy()
    recolored[10:118,35:90,:3] = [0,0,255]
    assert not image_continuity(image,Image.fromarray(recolored))["accepted"]


def test_mutation_gate_distinguishes_near_copies_from_growing_limbs():
    data = np.zeros((128,128,4),dtype="uint8")
    data[10:118,45:80] = [160,120,95,255]
    image = Image.fromarray(data)
    assert not image_continuity(image,image)["changed"]
    subtle = data.copy()
    subtle[10:118,45:80,0] += 2
    assert not image_continuity(image,Image.fromarray(subtle))["changed"]
    arm = data.copy()
    arm[25:55,80:115] = [160,120,95,255]
    growing = image_continuity(image,Image.fromarray(arm))
    assert growing["accepted"] and growing["changed"]
    face = data.copy()
    face[10:40,45:80,:3] = [70,45,35]
    changing_face = image_continuity(image,Image.fromarray(face))
    assert changing_face["accepted"] and changing_face["changed"]


def test_detail_projection_maps_volume_extent_to_generated_subject():
    density = np.zeros((64,)*3,dtype="float32")
    density[14:49,8:56,20:44] = 32
    rgba = encode_volume(density,np.full((64,64,64,3),.2))
    image = np.zeros((128,128,4),dtype="uint8")
    image[12:116,30:98] = [240,60,30,255]
    sx,ox,sy,oy = front_projection(rgba,Image.fromarray(image))
    assert 20/63*sx+ox == pytest.approx(30/127)
    assert 43/63*sx+ox == pytest.approx(97/127)
    assert 55/63*sy+oy == pytest.approx(12/127)
    assert 8/63*sy+oy == pytest.approx(115/127)
