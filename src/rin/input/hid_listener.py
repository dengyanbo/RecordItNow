"""HID / Bluetooth listener backed by ``hidapi``.

Generic HID button decoding is messy (every device has its own report
descriptor). This module opens the device by ``(vendor_id, product_id)``
and emits press / release events whenever any byte in the input report
transitions between zero and non-zero. That covers presenter remotes,
Bluetooth media buttons, and similar one-button accessories.

For richer devices (multi-button gamepads, etc.) we'd need per-device
parsers; the architecture leaves room for that without changing callers.
"""
from __future__ import annotations

import contextlib
import threading
import time

from ..utils.logging import get_logger
from .base import EventCallback, InputEvent, ListenerBase

log = get_logger(__name__)


class HIDListener(ListenerBase):
    r"""Polls one HID device and reports any-byte-transition as press/release.

    Parameters
    ----------
    callback
        Where to push :class:`InputEvent`\ s.
    vendor_id, product_id
        Device selectors.
    usage_page, usage
        Optional logical channel for matching with the binding.
    poll_interval_seconds
        How often to retry opening the device if it disappears (Bluetooth
        idle disconnects). Kept low so reconnections happen quickly.
    """

    def __init__(
        self,
        callback: EventCallback,
        *,
        vendor_id: int,
        product_id: int,
        usage_page: int | None = None,
        usage: int | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        super().__init__(callback)
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.usage_page = usage_page
        self.usage = usage
        self.poll_interval_seconds = poll_interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"HIDListener-{self.vendor_id:04x}:{self.product_id:04x}", daemon=True
        )
        self._running = True
        self._thread.start()
        log.info(
            f"HID listener started for vid={self.vendor_id:#06x} pid={self.product_id:#06x}"
        )

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    # --- internals ----------------------------------------------------------------

    def _run(self) -> None:  # pragma: no cover - hardware loop
        try:
            import hid
        except ImportError:
            log.warning("hid package not available; HID listener disabled")
            self._running = False
            return

        device = None
        last_active = False
        while not self._stop_event.is_set():
            if device is None:
                try:
                    device = hid.device()
                    device.open(self.vendor_id, self.product_id)
                    device.set_nonblocking(True)
                except OSError:
                    device = None
                    self._stop_event.wait(self.poll_interval_seconds)
                    continue

            try:
                report = device.read(64, timeout_ms=50) or []
            except OSError:
                device = None
                last_active = False
                continue

            if not report:
                time.sleep(0.005)
                continue

            active = any(b != 0 for b in report[1:])
            if active and not last_active:
                self._emit("press")
            elif not active and last_active:
                self._emit("release")
            last_active = active

        if device is not None:
            with contextlib.suppress(OSError):
                device.close()

    def _emit(self, kind: str) -> None:  # pragma: no cover - hardware loop
        self.emit(
            InputEvent(
                kind=kind,  # type: ignore[arg-type]
                source="hid",
                identifier=f"{self.vendor_id:04x}:{self.product_id:04x}",
                vendor_id=self.vendor_id,
                product_id=self.product_id,
                usage_page=self.usage_page,
                usage=self.usage,
                timestamp_ms=InputEvent.now_ms(),
            )
        )
