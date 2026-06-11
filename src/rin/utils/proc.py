"""Subprocess helpers that keep RIN's child processes invisible.

RIN ships as a *windowed* executable (``console=False`` in
``scripts/RIN.spec``). On Windows, when a windowed process spawns a
console application such as ``ffmpeg`` or ``copilot``, the OS allocates a
brand-new console window that flashes on screen for the lifetime of the
child. During the capture/analyze loop these subprocesses fire
repeatedly and unattended, so the flashing cmd/terminal windows are
visually jarring.

``CREATE_NO_WINDOW`` tells Windows not to allocate that console. It is a
Windows-only creation flag (and is *not* defined on the stdlib
``subprocess`` module on other platforms), so :func:`no_window_kwargs`
returns an empty mapping everywhere else and is always safe to splat into
a ``subprocess.run`` / ``subprocess.Popen`` call::

    subprocess.run(args, **no_window_kwargs())

The flag only suppresses the console window; it does **not** detach the
child's standard handles, so stdin/stdout/stderr pipes (e.g. the ``q``
byte RIN writes to ffmpeg's stdin) keep working.
"""
from __future__ import annotations

import subprocess
import sys

__all__ = ["CREATE_NO_WINDOW", "no_window_kwargs"]

# 0x08000000. Defined on the stdlib ``subprocess`` module on Windows only;
# fall back to 0 elsewhere so references stay import-safe cross-platform.
CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def no_window_kwargs() -> dict[str, int]:
    """Return ``subprocess`` kwargs that suppress a console window on Windows.

    Returns ``{"creationflags": CREATE_NO_WINDOW}`` on Windows and an
    empty dict on every other platform, so call sites stay cross-platform
    and tests that mock the spawn never have to special-case the flag.
    """

    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
