"""Small JPEG thumbnail helper for capture previews."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def make_thumbnail(
    src_image: Path,
    dst: Path,
    size: tuple[int, int] = (240, 135),
) -> Path:
    """Write a 240x135 RGB JPEG thumbnail for ``src_image`` to ``dst``."""

    src_image = Path(src_image)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src_image) as img:
        thumb = ImageOps.fit(img.convert("RGB"), size, method=Image.Resampling.LANCZOS)
        thumb.save(dst, format="JPEG", quality=80)
    return dst
