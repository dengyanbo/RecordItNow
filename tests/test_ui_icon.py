"""Icon factory smoke tests."""
from __future__ import annotations

from PySide6.QtGui import QColor

from rin.ui.icon import icon_size_for, make_icon, make_recording_icon, tinted_icon


def test_make_icon_returns_non_null(qapp) -> None:
    icon = make_icon()
    assert not icon.isNull()
    pm = icon.pixmap(64, 64)
    assert pm.width() == 64
    assert pm.height() == 64


def test_make_recording_icon_differs_from_base(qapp) -> None:
    base = make_icon().pixmap(64, 64).toImage()
    rec = make_recording_icon().pixmap(64, 64).toImage()
    assert base != rec


def test_tinted_icon_recolors_svg(qapp) -> None:
    """``tinted_icon`` should produce a non-null QIcon whose pixmap
    contains pixels of the requested colour (≥ 1 pixel of approximately
    the tint colour)."""

    icon = tinted_icon("camera", "#FF00FF", sizes=(32,))
    assert not icon.isNull()
    pm = icon.pixmap(32, 32)
    img = pm.toImage()
    found = False
    target = QColor("#FF00FF")
    for y in range(0, 32, 2):
        for x in range(0, 32, 2):
            c = QColor(img.pixel(x, y))
            if c.alpha() == 0:
                continue
            if (
                abs(c.red() - target.red()) < 12
                and abs(c.green() - target.green()) < 12
                and abs(c.blue() - target.blue()) < 12
            ):
                found = True
                break
        if found:
            break
    assert found, "tinted SVG did not contain any pixels in the target color"


def test_tinted_icon_missing_asset_returns_empty(qapp) -> None:
    # When the asset is missing we should still return *some* QIcon (so
    # callers don't have to check for None), but no exception is raised.
    icon = tinted_icon("definitely-not-an-asset", "#000000", sizes=(16,))
    assert icon is not None


def test_icon_size_for_returns_sensible_sizes() -> None:
    assert icon_size_for("nav").width() == 18
    assert icon_size_for("menu").width() == 16
    assert icon_size_for("empty-state").width() == 40
    # Unknown rule falls back to default.
    assert icon_size_for("nonexistent").width() == icon_size_for("default").width()
