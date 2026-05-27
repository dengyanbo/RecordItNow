"""Tray + recording icons rendered from bundled Fluent SVG assets.

We compose two layers on each rendered pixmap:

1. A solid rounded-square background in the active accent color.
2. The Fluent ``camera`` SVG, recolored white, painted on top.

The recording variant adds a pulsing red dot in the lower-right corner.
:class:`PulseIconAnimator` is a tiny QObject helper that owns a QTimer
and updates a target ``QSystemTrayIcon`` every 150 ms during recording.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import LIGHT, Theme

_ASSETS = Path(__file__).resolve().parent / "assets"

# Sizes Windows reads from a multi-resolution QIcon (16/24/32/48/64 px).
_ICON_SIZES = (16, 24, 32, 48, 64)


def _render_camera_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """Paint the bundled ``camera.svg`` recolored to ``color`` inside ``rect``."""

    svg_path = _ASSETS / "camera.svg"
    if not svg_path.exists():
        # Fallback: draw a basic circle so we always show *something*.
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        return

    raw = svg_path.read_bytes().decode("utf-8", errors="replace")
    # Microsoft's Fluent SVGs use ``fill="black"`` or ``fill="currentColor"``.
    tinted = raw.replace('fill="black"', f'fill="{color.name()}"')
    tinted = tinted.replace('"currentColor"', f'"{color.name()}"')
    renderer = QSvgRenderer(tinted.encode("utf-8"))
    renderer.render(painter, rect)


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
