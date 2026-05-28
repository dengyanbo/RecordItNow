"""Reusable indeterminate progress widgets.

* :class:`Spinner` — a small rotating-arc widget (16-64 px). Drawn from
  scratch with :class:`QPainter` so we don't ship an animated GIF or
  pull in a heavier QML layer. ~30 FPS.
* :class:`BusyOverlay` — a semi-transparent surface that sits on top of
  any parent widget while a long-running task runs. Contains a centered
  spinner plus an optional message. Blocks mouse events to the parent
  while visible.

Both are theme-aware — call :meth:`Spinner.set_accent` (or
:meth:`BusyOverlay.set_palette`) when the active theme changes.

Typical use::

    from PySide6.QtCore import QRunnable, QThreadPool

    class _Task(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self._signals = signals

        def run(self) -> None:
            try:
                result = do_heavy_thing()
                self._signals.done.emit(result)
            except Exception as exc:
                self._signals.error.emit(str(exc))

    overlay = BusyOverlay(viewer_widget, message="Generating report…")
    pool = QThreadPool.globalInstance()
    overlay.show()
    pool.start(_Task(signals))
    # ... signals.done / signals.error wired to overlay.hide() + handle result
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from .theme import LIGHT, Theme


class Spinner(QWidget):
    """An indeterminate, rotating-arc progress indicator.

    Rotates a 90° accent arc around a faint full-circle track at ~30 FPS.
    No external assets — drawn with :class:`QPainter`.
    """

    DEFAULT_SIZE = 24
    DEFAULT_INTERVAL_MS = 33

    def __init__(
        self,
        *,
        size: int = DEFAULT_SIZE,
        accent: str | None = None,
        track_alpha: int = 60,
        thickness: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = max(12, size)
        self._thickness = thickness if thickness is not None else max(2.0, self._size / 10)
        self._accent = QColor(accent) if accent else QColor("#0078D4")
        self._track_alpha = max(0, min(255, track_alpha))
        self._phase = 0.0
        self.setFixedSize(self._size, self._size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._timer = QTimer(self)
        self._timer.setInterval(self.DEFAULT_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # --- public API ---------------------------------------------------------

    def set_accent(self, color: str) -> None:
        """Recolour the rotating arc + track. Safe to call at any time."""

        self._accent = QColor(color)
        self.update()

    def start(self) -> None:
        """Begin animating. No-op if already running."""

        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop animating. Safe to call when already stopped."""

        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    # --- Qt overrides -------------------------------------------------------

    def showEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle
        super().hideEvent(event)
        self.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.045) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - paint code
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            margin = self._thickness / 2 + 1
            rect = QRectF(
                margin,
                margin,
                self._size - 2 * margin,
                self._size - 2 * margin,
            )

            # Faint full-circle track.
            track_color = QColor(self._accent)
            track_color.setAlpha(self._track_alpha)
            pen = QPen(track_color, self._thickness, Qt.PenStyle.SolidLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 0, 360 * 16)

            # 90° rotating accent arc.
            pen.setColor(self._accent)
            painter.setPen(pen)
            # Qt drawArc: positive angle = counter-clockwise from 3 o'clock.
            # Negate so the visible rotation feels "natural" (clockwise).
            start_angle = -int(self._phase * 360 * 16)
            span = -(90 * 16)
            painter.drawArc(rect, start_angle, span)
        finally:
            painter.end()


class BusyOverlay(QWidget):
    """Semi-transparent overlay with a centered :class:`Spinner` + message.

    Reparented to a host widget; on ``show()`` resizes to fill the host
    and raises above siblings. Pointer events are absorbed so the host's
    interactive controls can't be clicked while busy. Caller is
    responsible for stopping the underlying work — this widget just
    *displays* the busy state.
    """

    OBJECT_NAME = "busy_overlay"

    def __init__(
        self,
        parent: QWidget,
        *,
        message: str = "",
        theme: Theme | None = None,
        spinner_size: int = 32,
    ) -> None:
        super().__init__(parent)
        theme = theme or LIGHT
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Soak up clicks so the user can't double-fire the operation.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAutoFillBackground(False)

        self._theme = theme
        self._spinner = Spinner(size=spinner_size, accent=theme.accent, parent=self)
        self._message = QLabel(message)
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setProperty("role", "empty-state-hint")
        # Status messages are short — keep them single-line so word wrap
        # doesn't truncate inside the cramped overlay layout.
        self._message.setWordWrap(False)
        self._message.setMinimumHeight(24)
        self._message.setVisible(bool(message))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch()
        layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._message, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

        # Watch parent resize events so we always cover its full area.
        parent.installEventFilter(self)
        self.hide()

    # --- public API ---------------------------------------------------------

    def set_message(self, text: str) -> None:
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def message(self) -> str:
        return self._message.text()

    def set_theme(self, theme: Theme) -> None:
        """Re-tint the spinner + background. Call when the global theme changes."""

        self._theme = theme
        self._spinner.set_accent(theme.accent)
        self.update()

    # --- Qt overrides -------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(0, 0, self.parentWidget().width(), self.parentWidget().height())
        return False

    def showEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())
        self.raise_()
        self._spinner.start()

    def hideEvent(self, event) -> None:  # pragma: no cover - Qt lifecycle
        super().hideEvent(event)
        self._spinner.stop()

    def paintEvent(self, event) -> None:  # pragma: no cover - paint code
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg = QColor(self._theme.surface)
            bg.setAlpha(210)
            painter.fillRect(self.rect(), bg)
        finally:
            painter.end()


__all__ = ["BusyOverlay", "Spinner"]


# Silence "imported but unused" warning for the QObject import that is
# only used as a type reference in eventFilter signature on some IDEs.
_ = QObject
