"""OCR wrapper tests with a stubbed engine."""
from __future__ import annotations

from pathlib import Path

from rin.analysis import ocr


class _FakeEngine:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __call__(self, _path: str):
        return [[None, line, 0.95] for line in self._lines], 0.01


def test_extract_text_joins_engine_output(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    ocr.reset_engine()
    monkeypatch.setattr(ocr, "_get_engine", lambda: _FakeEngine(["Hello", "World"]))
    out = ocr.extract_text(img)
    assert out == "Hello\nWorld"


def test_extract_text_returns_empty_when_engine_unavailable(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    ocr.reset_engine()
    monkeypatch.setattr(ocr, "_get_engine", lambda: None)
    assert ocr.extract_text(img) == ""


def test_extract_text_swallows_engine_exceptions(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")

    class _BoomEngine:
        def __call__(self, _path):
            raise RuntimeError("boom")

    ocr.reset_engine()
    monkeypatch.setattr(ocr, "_get_engine", lambda: _BoomEngine())
    assert ocr.extract_text(img) == ""
