"""Autostart helper tests with a stubbed winreg module."""
from __future__ import annotations

import sys

import pytest

from rin.utils import autostart


class _FakeKey:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self._name = name

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.store: dict = {}

    def OpenKey(self, _hkey, subkey, _reserved, _access):
        return _FakeKey(self.store, subkey)

    def QueryValueEx(self, _key, name):
        if name not in self.store:
            raise FileNotFoundError(name)
        return (self.store[name], self.REG_SZ)

    def SetValueEx(self, _key, name, _reserved, _type, value):
        self.store[name] = value

    def DeleteValue(self, _key, name):
        if name not in self.store:
            raise FileNotFoundError(name)
        del self.store[name]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeWinreg:
    monkeypatch.setattr(sys, "platform", "win32")
    f = _FakeWinreg()
    monkeypatch.setattr(autostart, "_winreg", lambda: f)
    return f


def test_is_enabled_false_when_missing(fake: _FakeWinreg) -> None:
    assert autostart.is_enabled() is False


def test_enable_then_is_enabled(fake: _FakeWinreg) -> None:
    assert autostart.enable("C:\\rin.exe") is True
    assert autostart.is_enabled() is True
    assert fake.store["RIN"] == "C:\\rin.exe"


def test_disable_removes_entry(fake: _FakeWinreg) -> None:
    autostart.enable("C:\\rin.exe")
    assert autostart.disable() is True
    assert autostart.is_enabled() is False


def test_non_windows_helpers_are_noops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(autostart, "_winreg", lambda: None)
    assert autostart.is_enabled() is False
    assert autostart.enable("x") is False
    assert autostart.disable() is False


def test_default_command_returns_string() -> None:
    cmd = autostart.default_command()
    assert isinstance(cmd, str)
    assert "rin" in cmd.lower()
