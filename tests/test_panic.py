"""Panic hotkey tests with a stubbed ``keyboard`` module."""
from __future__ import annotations

import sys

import pytest

from rin.utils.panic import PanicHotkey


class _FakeKeyboard:
    def __init__(self) -> None:
        self.added: list[tuple[str, object]] = []
        self.removed: list = []

    def add_hotkey(self, hotkey: str, callback):
        handle = object()
        self.added.append((hotkey, callback))
        return handle

    def remove_hotkey(self, handle) -> None:
        self.removed.append(handle)


@pytest.fixture
def fake_kb(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyboard:
    fake = _FakeKeyboard()
    monkeypatch.setitem(sys.modules, "keyboard", fake)  # type: ignore[arg-type]
    return fake


def test_install_registers_hotkey(fake_kb: _FakeKeyboard) -> None:
    called: list = []
    hk = PanicHotkey(lambda: called.append(True))
    assert hk.install() is True
    assert fake_kb.added[0][0] == "ctrl+alt+shift+p"


def test_uninstall_removes_hotkey(fake_kb: _FakeKeyboard) -> None:
    hk = PanicHotkey(lambda: None)
    hk.install()
    hk.uninstall()
    assert len(fake_kb.removed) == 1


def test_callback_invoked_on_hotkey(fake_kb: _FakeKeyboard) -> None:
    called: list = []
    hk = PanicHotkey(lambda: called.append(True))
    hk.install()
    # Manually trigger the registered callback.
    _hotkey, cb = fake_kb.added[0]
    cb()
    assert called == [True]


def test_callback_exception_is_swallowed(fake_kb: _FakeKeyboard) -> None:
    def boom() -> None:
        raise RuntimeError("nope")

    hk = PanicHotkey(boom)
    hk.install()
    fake_kb.added[0][1]()  # must not raise


def test_install_returns_false_when_keyboard_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force ImportError when PanicHotkey.install tries to `import keyboard`.
    monkeypatch.setitem(sys.modules, "keyboard", None)
    hk = PanicHotkey(lambda: None)
    assert hk.install() is False
