"""UI layer (system tray + settings dialogs).

Phase 4 wires everything together: the tray icon owns the
:class:`~rin.input.InputManager` and :class:`~rin.capture.CaptureService`
and exposes a menu (Capture / Settings / Reports / Search / Pause / Quit).

v0.3.0+ adds the Fluent-inspired theme + bundled SVG icons under
``assets/``. :func:`icon_path` returns the absolute path of a bundled
icon, used by both QIcon factories and stylesheets that need
``url(...)`` references.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .icon import icon_size_for, make_icon, make_recording_icon, tinted_icon
from .notifications import notify
from .progress import BusyOverlay, Spinner
from .style import palette_to_qss
from .theme import (
    ACCENTS,
    DARK,
    LIGHT,
    Theme,
    contrast_ratio,
    current_theme,
    resolve,
    system_theme,
    with_accent,
)
from .tray import TrayApp

if TYPE_CHECKING:
    from .settings_dialog import SettingsDialog

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def __getattr__(name: str):
    """Lazily resolve heavy re-exports so they stay off the startup path.

    ``SettingsDialog`` (and its large tab/PoI tree) is only needed when the
    user opens Settings; importing it here would load ~2500 LOC of UI at boot.
    ``from rin.ui import SettingsDialog`` still works — attribute access
    triggers the import on demand (PEP 562).
    """

    if name == "SettingsDialog":
        from .settings_dialog import SettingsDialog

        return SettingsDialog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def icon_path(name: str) -> Path:
    """Return the absolute path to ``name.svg`` under ``assets/``.

    Raises :class:`FileNotFoundError` if the asset isn't bundled.
    """

    p = _ASSETS_DIR / f"{name}.svg"
    if not p.exists():
        raise FileNotFoundError(f"UI asset not found: {p}")
    return p


__all__ = [
    "ACCENTS",
    "DARK",
    "LIGHT",
    "BusyOverlay",
    "SettingsDialog",
    "Spinner",
    "Theme",
    "TrayApp",
    "contrast_ratio",
    "current_theme",
    "icon_path",
    "icon_size_for",
    "make_icon",
    "make_recording_icon",
    "notify",
    "palette_to_qss",
    "resolve",
    "system_theme",
    "tinted_icon",
    "with_accent",
]
