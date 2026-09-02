from PIL import Image, ImageDraw

from video_to_notes.visual.image_metrics import (
    changed_pixel_ratio,
    hamming_distance,
    phash,
)


def test_identical_images(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (320, 180), "white").save(a)
    Image.new("RGB", (320, 180), "white").save(b)

    assert changed_pixel_ratio(a, b) == 0.0
    assert hamming_distance(phash(a), phash(b)) == 0


def test_changed_region_detected(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"

    Image.new("RGB", (320, 180), "white").save(a)
    im = Image.new("RGB", (320, 180), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((80, 40, 240, 140), fill="black")
    im.save(b)

    assert changed_pixel_ratio(a, b) > 0.1
