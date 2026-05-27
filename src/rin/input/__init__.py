"""Input layer.

Exposes the high-level :class:`InputManager` that owns the keyboard,
mouse, and HID listeners, and routes their events into a
:class:`GestureRecognizer`. The recognizer translates raw press/release
events into the higher-level *tap* (screenshot) and *hold* (start/stop
recording) gestures the rest of the app consumes via Qt signals.
"""
from __future__ import annotations

from .base import EventKind, InputEvent, ListenerBase, binding_matches_event
from .gesture import GestureRecognizer, GestureState, GestureStateMachine
from .learn_mode import LearnRecorder
from .manager import InputManager

__all__ = [
    "EventKind",
    "GestureRecognizer",
    "GestureState",
    "GestureStateMachine",
    "InputEvent",
    "InputManager",
    "LearnRecorder",
    "ListenerBase",
    "binding_matches_event",
]
