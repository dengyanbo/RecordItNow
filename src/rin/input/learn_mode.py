"""Learn-mode: bind whatever the user presses next.

The settings dialog (Phase 4) prompts the user to press their preferred
trigger; the next *press* event we receive from any source is converted
to a :class:`~rin.config.TriggerBinding` and returned. ``stop()`` is
called either by timeout or after the binding is captured.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from ..config import TriggerBinding
from ..utils.logging import get_logger
from .base import InputEvent
from .reserved_keys import Severity, lookup_reserved

log = get_logger(__name__)


class LearnRecorder:
    """Collect the first press event and convert it to a ``TriggerBinding``."""

    def __init__(
        self,
        *,
        hold_threshold_ms: int = 500,
        on_captured: Callable[[TriggerBinding], None] | None = None,
    ) -> None:
        self.hold_threshold_ms = hold_threshold_ms
        self.on_captured = on_captured
        self._captured: TriggerBinding | None = None
        self._done = threading.Event()
        # Populated by ``handle_event`` if the captured binding collides
        # with a known reserved key (see ``reserved_keys.RESERVED_KEYS``).
        # ``None`` means "no known conflict" — not necessarily safe, just
        # not on our radar.
        self._reserved_warning: tuple[str, Severity] | None = None

    @property
    def captured(self) -> TriggerBinding | None:
        return self._captured

    @property
    def reserved_warning(self) -> tuple[str, Severity] | None:
        """Return ``(reason, severity)`` if the captured binding is reserved.

        Callers (e.g. the Settings dialog) can surface this to the user
        as a warning or block save outright on ``severity == "error"``.
        """

        return self._reserved_warning

    def handle_event(self, event: InputEvent) -> None:
        if self._done.is_set() or event.kind != "press":
            return
        binding = TriggerBinding(
            source=event.source,
            key=event.identifier if event.source in {"keyboard", "mouse"} else None,
            vendor_id=event.vendor_id,
            product_id=event.product_id,
            usage_page=event.usage_page,
            usage=event.usage,
            hold_threshold_ms=self.hold_threshold_ms,
            label=_default_label(event),
        )
        self._captured = binding
        self._reserved_warning = lookup_reserved(binding)
        self._done.set()
        if self._reserved_warning is not None:
            reason, severity = self._reserved_warning
            log.warning(
                "Learn-mode captured a reserved binding "
                f"({severity}): {binding} — {reason}"
            )
        else:
            log.info(f"Learn-mode captured binding: {binding}")
        if self.on_captured is not None:
            self.on_captured(binding)

    def wait(self, timeout_seconds: float | None = None) -> TriggerBinding | None:
        if self._done.wait(timeout=timeout_seconds):
            return self._captured
        return None


def _default_label(event: InputEvent) -> str:
    if event.source == "keyboard":
        return f"Key: {event.identifier}"
    if event.source == "mouse":
        return f"Mouse {event.identifier}"
    return f"HID {event.vendor_id:#06x}:{event.product_id:#06x}"
