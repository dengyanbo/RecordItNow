"""Icon factory smoke tests."""
from __future__ import annotations

from rin.ui.icon import make_icon, make_recording_icon


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
