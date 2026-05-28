"""Tray + recording icons rendered from bundled Fluent SVG assets.

We compose two layers on each rendered pixmap:

1. A solid rounded-square background in the active accent color.
2. The Fluent ``camera`` SVG, recolored white, painted on top.

The recording variant adds a pulsing red dot in the lower-right corner.
:class:`PulseIconAnimator` is a tiny QObject helper that owns a QTimer
and updates a target ``QSystemTrayIcon`` every 150 ms during recording.

This module also exposes :func:`tinted_icon`, which loads any bundled
asset and recolors it for a given foreground colour. Used by the nav
rail, settings menu actions, and empty-state placeholders so icons
always read crisply against the active theme.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import LIGHT, Theme

_ASSETS = Path(__file__).resolve().parent / "assets"

# Sizes Windows reads from a multi-resolution QIcon (16/24/32/48/64 px).
_ICON_SIZES = (16, 24, 32, 48, 64)


@lru_cache(maxsize=64)
def _read_svg(name: str) -> str:
    """Return the raw text of ``<name>.svg`` from the bundled assets.

    Cached because the same asset is rendered at many sizes — re-reading
    the file each time is wasteful (the SVGs are small but the lookup is
    on a hot rendering path).
    """

    path = _ASSETS / f"{name}.svg"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _tint_svg_text(text: str, color: str) -> str:
    """Replace common Fluent-SVG fill markers with ``color``."""

    if not text:
        return text
    # Microsoft Fluent UI System Icons use fill="#212121" (light)
    # or fill="currentColor". Match a few common forms.
    out = text
    for needle in ('fill="#212121"', 'fill="#000000"', 'fill="black"'):
        out = out.replace(needle, f'fill="{color}"')
    out = out.replace('"currentColor"', f'"{color}"')
    return out


def _render_camera_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """Paint the bundled ``camera.svg`` recolored to ``color`` inside ``rect``."""

    raw = _read_svg("camera")
    if not raw:
        # Fallback: draw a basic circle so we always show *something*.
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        return
    renderer = QSvgRenderer(_tint_svg_text(raw, color.name()).encode("utf-8"))
    renderer.render(painter, rect)


def _render_tinted_pixmap(name: str, size: int, color: str) -> QPixmap:
    """Render ``name.svg`` at ``size`` px square, fill recoloured to ``color``."""

    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    raw = _read_svg(name)
    if not raw:
        return pm
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer = QSvgRenderer(_tint_svg_text(raw, color).encode("utf-8"))
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    return pm


def tinted_icon(name: str, color: str, *, sizes: tuple[int, ...] = (16, 20, 24, 32)) -> QIcon:
    """Return a multi-resolution :class:`QIcon` for ``name.svg`` filled
    with ``color`` (any ``#rrggbb`` string).

    Suitable for nav-rail items, menu actions, empty-state placeholders,
    and buttons that need to match the active theme.
    """

    icon = QIcon()
    for s in sizes:
        icon.addPixmap(_render_tinted_pixmap(name, s, color))
    return icon


def icon_size_for(rule: str = "default") -> QSize:
    """Canonical icon sizes used across the app."""

    return {
        "nav": QSize(18, 18),
        "menu": QSize(16, 16),
        "card": QSize(24, 24),
        "empty-state": QSize(40, 40),
        "button": QSize(16, 16),
        "default": QSize(20, 20),
    }.get(rule, QSize(20, 20))


def _make_pixmap(size: int, theme: Theme = LIGHT, recording: bool = False,
                 pulse_phase: float = 0.0) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background pill in the accent color.
        bg = QColor(theme.accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        radius = max(2, size // 5)
        painter.drawRoundedRect(0, 0, size, size, radius, radius)

        # Inset camera glyph (about 60 % of the icon size, centered).
        inset = size * 0.20
        glyph_rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
        _render_camera_glyph(painter, glyph_rect, QColor(theme.on_accent))

        # Recording badge: pulsing red dot in the lower-right quadrant.
        if recording:
            d = max(4, size // 3)
            # 0.5 .. 1.0 pulse using a half-sine.
            alpha = int(180 + 75 * math.sin(pulse_phase * 2 * math.pi))
            dot = QColor("#E81123")
            dot.setAlpha(max(120, min(255, alpha)))
            painter.setBrush(QBrush(dot))
            painter.setPen(QPen(QColor(theme.on_accent), max(1, size // 32)))
            painter.drawEllipse(
                size - d - max(1, size // 16),
                size - d - max(1, size // 16),
                d,
                d,
            )
    finally:
        painter.end()
    return pm


def _multi_size_icon(theme: Theme = LIGHT, recording: bool = False,
                     pulse_phase: float = 0.0) -> QIcon:
    icon = QIcon()
    for s in _ICON_SIZES:
        icon.addPixmap(_make_pixmap(s, theme, recording, pulse_phase))
    return icon


def make_icon(size: int = 64, theme: Theme = LIGHT) -> QIcon:
    """Return the idle tray icon (camera glyph on accent background)."""

    if size == 64:
        return _multi_size_icon(theme)
    return QIcon(_make_pixmap(size, theme))


def make_recording_icon(size: int = 64, theme: Theme = LIGHT,
                        pulse_phase: float = 0.0) -> QIcon:
    """Return the recording-state tray icon (idle icon + pulsing red dot)."""

    if size == 64:
        return _multi_size_icon(theme, recording=True, pulse_phase=pulse_phase)
    return QIcon(_make_pixmap(size, theme, recording=True, pulse_phase=pulse_phase))


class PulseIconAnimator(QObject):
    """Drives the pulsing red dot on the recording tray icon.

    Owns a :class:`QTimer`; while ``active`` is True, ticks every
    ``interval_ms`` and updates the target tray's icon with a fresh
    ``make_recording_icon(pulse_phase=…)``.
    """

    def __init__(self, tray, theme: Theme = LIGHT, *, interval_ms: int = 150,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray = tray
        self.theme = theme
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._phase = 0.0
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self._tray.setIcon(make_icon(theme=self.theme))

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        if self._timer.isActive():
            self._tick()
        else:
            self._tray.setIcon(make_icon(theme=theme))

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % 1.0
        self._tray.setIcon(make_recording_icon(theme=self.theme, pulse_phase=self._phase))
