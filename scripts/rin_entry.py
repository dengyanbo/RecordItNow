"""PyInstaller entry script for the standalone RIN .exe.

PyInstaller bundles whatever script you point ``Analysis(...)`` at as
the top-level entry. If that script is ``src/rin/__main__.py``, the
PyInstaller bootloader runs it WITHOUT setting ``__package__='rin'``,
so any ``from .X import Y`` raises ``ImportError: attempted relative
import with no known parent package``.

This entry script lives OUTSIDE the ``rin`` package so it can use a
clean absolute import. ``rin`` is bundled separately via the spec's
``pathex`` + ``collect_submodules`` hooks and gets registered in the
PYZ archive, so ``import rin.__main__`` here resolves to the bundled
package module.
"""
from __future__ import annotations

import sys

from rin.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
