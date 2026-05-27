"""Smoke test that the rendered QSS is accepted by QApplication."""
from __future__ import annotations

from rin.ui.style import palette_to_qss
from rin.ui.theme import DARK, LIGHT


def test_qapplication_accepts_light_stylesheet(qapp) -> None:
    qss = palette_to_qss(LIGHT)
    qapp.setStyleSheet(qss)
    # Round-trip: setStyleSheet stores exactly what we pass.
    assert qapp.styleSheet() == qss


def test_qapplication_accepts_dark_stylesheet(qapp) -> None:
    qss = palette_to_qss(DARK)
    qapp.setStyleSheet(qss)
    assert qapp.styleSheet() == qss
    # Restore for downstream tests.
    qapp.setStyleSheet("")
