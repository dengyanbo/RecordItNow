"""Thin wrapper over ``QSystemTrayIcon.showMessage`` with safe fallbacks."""
from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon

from ..utils.logging import get_logger

log = get_logger(__name__)

_tray_ref: QSystemTrayIcon | None = None


def attach(tray: QSystemTrayIcon) -> None:
    """Register the tray used for delivering toasts."""

    global _tray_ref
    _tray_ref = tray


def notify(title: str, body: str = "", *, level: str = "info", msecs: int = 4000) -> None:
    """Send a toast notification. Logs and degrades gracefully if no tray is registered."""

    log.info(f"[notify:{level}] {title}" + (f" — {body}" if body else ""))
    if _tray_ref is None or not _tray_ref.isVisible():
        return
    icon = {
        "info": QSystemTrayIcon.MessageIcon.Information,
        "warning": QSystemTrayIcon.MessageIcon.Warning,
        "error": QSystemTrayIcon.MessageIcon.Critical,
    }.get(level, QSystemTrayIcon.MessageIcon.Information)
    _tray_ref.showMessage(title, body, icon, msecs)
