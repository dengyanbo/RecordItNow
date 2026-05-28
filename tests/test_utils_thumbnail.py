from __future__ import annotations

from pathlib import Path

from PIL import Image

from rin.utils.thumbnail import make_thumbnail


def test_make_thumbnail_writes_rgb_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    dst = tmp_path / "source.jpg"
    Image.new("RGBA", (640, 360), (20, 40, 200, 128)).save(src)

    assert make_thumbnail(src, dst) == dst

    with Image.open(dst) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (240, 135)
