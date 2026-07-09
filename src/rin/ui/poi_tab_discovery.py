"""Asynchronous discovery worker plumbing for the Topics & PoIs settings UI."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from ..config import RinConfig
from ..poi.discovery import discover, persist_candidates


class _DiscoverySignals(QObject):
    done = Signal(int)
    failed = Signal(str)


class _DiscoveryTask(QRunnable):
    def __init__(self, cfg: RinConfig, signals: _DiscoverySignals) -> None:
        super().__init__()
        self._cfg = cfg
        self._signals = signals

    def run(self) -> None:
        try:
            drafts = discover(self._cfg, days=14)
            inserted_ids = persist_candidates(drafts)
            self._signals.done.emit(len(inserted_ids))
        except Exception as exc:
            self._signals.failed.emit(str(exc))



__all__ = ["_DiscoverySignals", "_DiscoveryTask"]
