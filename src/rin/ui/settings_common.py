"""Shared constants, option lists, worker plumbing, and small helpers for
the Settings dialog.

Split out of ``settings_dialog.py`` so the dialog module carries the UI
logic (tabs + load/save) rather than also owning thread plumbing, option
tables, and layout micro-helpers. Nothing here is public API — it's
imported only by ``settings_dialog.py``.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from ..utils import updater
from ..utils.logging import get_logger

log = get_logger(__name__)


# --- option tables ------------------------------------------------------------

LLM_NAMES = ["copilot_cli", "openai", "azure", "none"]
REPORT_FREQUENCIES = ["daily", "weekly", "off"]
REASONING_EFFORTS = ["", "none", "low", "medium", "high", "xhigh", "max"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
THEME_MODES = ["auto", "light", "dark"]
ACCENT_OPTIONS = ["blue", "purple", "teal", "orange"]
OCR_LANGUAGE_OPTIONS = [
    ("en", "English"),
    ("ch_sim", "Chinese (Simplified)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
]
WHISPER_MODEL_OPTIONS = ["tiny", "base", "small", "medium", "large-v3"]
WHISPER_MODEL_HINTS = {
    "tiny": "Memory hint: fastest startup, ~1 GB RAM on CPU.",
    "base": "Memory hint: balanced for short notes, ~1.5 GB RAM on CPU.",
    "small": "Memory hint: recommended default, ~2 GB RAM on CPU.",
    "medium": "Memory hint: higher accuracy, ~5 GB RAM on CPU.",
    "large-v3": "Memory hint: best accuracy, expect ~10 GB RAM on CPU.",
}

# Standard input-width tiers — picked from Fluent 2 form patterns. Used
# everywhere instead of ``setMaximumWidth`` (which doesn't honor a
# QFormLayout's row).
_W_NUMBER = 132   # numeric input with suffix (e.g. "500 ms")
_W_PICKER = 220   # short combo / dropdown
_W_TEXT = 360     # free-form short text (model name)
_W_URL = 460      # URL / long text


# --- small layout helpers -----------------------------------------------------


def _nav_icon(name: str, color: str) -> QIcon:
    """Return a tinted Fluent SVG icon for the nav rail (theme-aware)."""

    try:
        from .icon import tinted_icon

        return tinted_icon(name, color)
    except Exception:
        return QIcon()


def _wrap(layout) -> QWidget:
    """Wrap a layout in a transparent ``QWidget`` so it can sit in a ``QFormLayout``."""

    w = QWidget()
    w.setLayout(layout)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return w


# --- worker plumbing ----------------------------------------------------------


class _UpdateCheckSignals(QObject):
    finished = Signal(object)  # UpdateInfo | None


class _UpdateCheckWorker(QRunnable):
    """One-shot worker that calls the updater and emits the result on completion."""

    def __init__(self, *, force: bool) -> None:
        super().__init__()
        self.force = force
        self.signals = _UpdateCheckSignals()

    def run(self) -> None:  # pragma: no cover - thread plumbing
        try:
            info = updater.check_for_update(force=self.force)
        except Exception as exc:
            log.warning(f"Update check raised: {exc}")
            info = None
        self.signals.finished.emit(info)


class _AudioRefreshSignals(QObject):
    done = Signal(list)
    failed = Signal(str)


class _AudioRefreshTask(QRunnable):
    """Run :func:`list_dshow_audio_devices` on a worker thread."""

    def __init__(self, signals: _AudioRefreshSignals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - thread plumbing
        try:
            from ..capture import list_dshow_audio_devices

            devices = list(list_dshow_audio_devices())
            self._signals.done.emit(devices)
        except Exception as exc:
            self._signals.failed.emit(str(exc))
