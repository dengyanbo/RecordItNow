"""Shared pytest fixtures.

The ``isolated_data_dir`` fixture is autouse so every test runs against
a fresh, throwaway RIN data root. This prevents accidental writes to
the real ``%LOCALAPPDATA%\\RIN`` during local development.

The session-scoped ``qapp`` fixture provides a single ``QApplication``
shared by every test that needs Qt. We can't mix ``QCoreApplication``
and ``QApplication`` in the same process — ``QApplication.instance()``
returns whichever was created first — so always use ``QApplication``
even for tests that only need the event loop.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rin import paths


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "rin-data"
    monkeypatch.setenv("RIN_DATA_DIR", str(root))
    paths.reset_cache()
    yield root
    paths.reset_cache()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
