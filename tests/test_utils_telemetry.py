"""Tests for optional telemetry bootstrap."""
from __future__ import annotations

from types import SimpleNamespace

from rin.config import TelemetryConfig
from rin.utils import telemetry


def test_install_with_enabled_false_is_noop(monkeypatch) -> None:
    called: list[str] = []

    def fake_import(name: str):
        called.append(name)
        raise AssertionError("telemetry import should not happen when disabled")

    monkeypatch.setattr(telemetry.importlib, "import_module", fake_import)

    assert telemetry.install(TelemetryConfig(enabled=False, dsn="https://x@y/1")) is False
    assert called == []



def test_install_with_bad_dsn_is_logged_and_skipped(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        telemetry,
        "log",
        SimpleNamespace(info=lambda _msg: None, warning=warnings.append),
    )

    class _FakeSentry:
        @staticmethod
        def init(**_kwargs):
            raise ValueError("bad dsn")

    monkeypatch.setattr(telemetry.importlib, "import_module", lambda _name: _FakeSentry())

    assert telemetry.install(TelemetryConfig(enabled=True, dsn="not-a-dsn")) is False
    assert any("bad dsn" in msg.lower() for msg in warnings)
