"""Small JPEG thumbnail helper for capture previews."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def make_thumbnail_from_image(
    image: Image.Image,
    dst: Path,
    size: tuple[int, int] = (240, 135),
) -> Path:
    """Write a 240x135 RGB JPEG thumbnail from an in-memory PIL image.

    Used by the screenshot path so the thumbnail is derived from the frame
    already held in memory instead of re-reading (and re-decoding) the
    just-written capture file.
    """

    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    thumb = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    thumb.save(dst, format="JPEG", quality=80)
    return dst


def make_thumbnail(
    src_image: Path,
    dst: Path,
    size: tuple[int, int] = (240, 135),
) -> Path:
    """Write a 240x135 RGB JPEG thumbnail for ``src_image`` to ``dst``."""

    src_image = Path(src_image)
    with Image.open(src_image) as img:
        return make_thumbnail_from_image(img, dst, size)
