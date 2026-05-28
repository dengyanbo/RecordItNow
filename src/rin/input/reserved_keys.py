"""Reserved keyboard combinations that should not be bound as a RIN trigger.

Some keys never reach RIN's listener because Windows or the focused
application intercepts them; binding them silently breaks the trigger.
Others are technically capturable but breaking them creates a worse
user experience (e.g., binding Ctrl+C means every copy you do also
fires a screenshot).

The table here is intentionally small — we only list keys the
maintainers have personally hit during dogfooding or have explicit
Microsoft documentation for. Adding entries is encouraged; please cite
the source in a code comment.
"""
from __future__ import annotations

from typing import Literal

from ..config import TriggerBinding

Severity = Literal["error", "warning"]

# Maps the lowercased ``InputEvent.identifier`` (which mirrors
# ``TriggerBinding.key``) to a (reason, severity) tuple.
#
# ``error``   = will not work reliably or will visibly damage UX. Refuse.
# ``warning`` = will work but conflicts with a common shortcut. Warn.
RESERVED_KEYS: dict[str, tuple[str, Severity]] = {
    # System-reserved (Windows intercepts before app listeners)
    "ctrl+alt+delete":  ("Opens the secure-attention screen", "error"),
    "win+l":            ("Locks the workstation", "error"),
    "win+d":            ("Shows the desktop", "error"),
    "win+tab":          ("Opens Task View", "error"),
    "alt+tab":          ("Switches windows", "error"),
    "alt+f4":           ("Closes the focused window", "error"),
    "print_screen":     ("Captured by Snipping Tool / system clipboard", "warning"),

    # Common per-app shortcuts (works but creates friction)
    "ctrl+c":           ("System copy shortcut", "warning"),
    "ctrl+v":           ("System paste shortcut", "warning"),
    "ctrl+x":           ("System cut shortcut", "warning"),
    "ctrl+z":           ("System undo shortcut", "warning"),
    "ctrl+a":           ("Select-all shortcut", "warning"),
    "ctrl+s":           ("Save shortcut", "warning"),

    # Common function-key clashes
    "f1":               ("Often triggers Help in apps", "warning"),
    "f5":               ("Refreshes browsers and editors", "warning"),
    "f11":              ("Toggles fullscreen in browsers", "warning"),
    "f12":              ("Opens DevTools in browsers", "warning"),

    # Single-key dialog navigation (binding these breaks typing)
    "enter":            ("Activates the focused control", "error"),
    "tab":              ("Used for focus traversal", "error"),
    "esc":              ("Used to dismiss dialogs", "error"),
    "space":            ("Activates buttons; pages browsers", "warning"),
    "backspace":        ("Deletes text", "error"),
}


def lookup_reserved(binding: TriggerBinding) -> tuple[str, Severity] | None:
    """Return ``(reason, severity)`` if ``binding`` collides with a reserved
    combination, otherwise ``None``.

    Only keyboard bindings can collide. Mouse buttons and HID devices are
    not subject to OS-level interception (within reason) and are always
    accepted.

    Matching is case-insensitive and uses the same identifier the
    keyboard listener emits (lower-case, ``+``-separated modifiers, e.g.
    ``ctrl+c``).
    """

    if binding.source != "keyboard":
        return None
    if not binding.key:
        return None
    key = binding.key.strip().lower()
    return RESERVED_KEYS.get(key)


__all__ = ["RESERVED_KEYS", "Severity", "lookup_reserved"]
