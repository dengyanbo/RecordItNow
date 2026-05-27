"""Shared input types: source-agnostic press/release events + listener ABC.

Listeners (keyboard, mouse, HID) emit :class:`InputEvent` to a shared
callback. The gesture state machine and learn-mode subscribers don't
care which listener produced an event — only the source identifier and
key/button payload.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ..config import TriggerBinding

EventKind = Literal["press", "release"]

EventCallback = Callable[["InputEvent"], None]


@dataclass(frozen=True)
class InputEvent:
    kind: EventKind
    source: Literal["keyboard", "mouse", "hid"]
    # Source-dependent identifier. Keyboard: lower-case key name (e.g. "f12").
    # Mouse: button name (e.g. "x1"). HID: (vid, pid, usage_page, usage) tuple as str.
    identifier: str
    # Optional structured payload for richer matching (vendor/product ids for HID, etc.).
    vendor_id: int | None = None
    product_id: int | None = None
    usage_page: int | None = None
    usage: int | None = None
    timestamp_ms: float = 0.0

    @staticmethod
    def now_ms() -> float:
        return time.monotonic() * 1000.0


def binding_matches_event(binding: TriggerBinding, event: InputEvent) -> bool:
    """Return True if ``event`` matches the trigger binding."""

    if binding.source == "unset":
        return False
    if binding.source != event.source:
        return False
    if binding.source in {"keyboard", "mouse"}:
        return (binding.key or "").lower() == event.identifier.lower()
    if binding.source == "hid":
        return (
            binding.vendor_id == event.vendor_id
            and binding.product_id == event.product_id
            and (binding.usage_page is None or binding.usage_page == event.usage_page)
            and (binding.usage is None or binding.usage == event.usage)
        )
    return False


class ListenerBase(ABC):
    """Abstract listener. Implementations run their own threads."""

    def __init__(self, callback: EventCallback) -> None:
        self._callback = callback
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def emit(self, event: InputEvent) -> None:
        if self._running:
            self._callback(event)

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
