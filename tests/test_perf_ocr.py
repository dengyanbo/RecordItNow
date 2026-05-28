"""Benchmark image analysis with mocked OCR (target: ≤1.5s on a 320x240 PNG)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin.analysis import image_analyzer

pytest.importorskip("pytest_benchmark")
PIL_Image = pytest.importorskip("PIL.Image")


@pytest.fixture
def black_png(tmp_path: Path) -> Path:
    path = tmp_path / "black.png"
    PIL_Image.new("RGB", (320, 240), color="black").save(path)
    return path


@pytest.mark.benchmark(group="ocr")
def test_analyze_image_benchmark(
    monkeypatch: pytest.MonkeyPatch,
    black_png: Path,
    benchmark,
) -> None:
    """target: ≤1500ms on a 320x240 black PNG with mocked OCR."""

    def fake_extract_text(image_path: Path) -> str:
        with PIL_Image.open(image_path) as image:
            image.load()
            return f"{image.size[0]}x{image.size[1]}"

    monkeypatch.setattr(image_analyzer, "extract_text", fake_extract_text)
    summaries: list[str] = []

    def run_analysis() -> str:
        result = image_analyzer.analyze_image(black_png, provider=None)
        summaries[:] = [result.summary]
        return result.summary

    benchmark.pedantic(run_analysis, rounds=5, iterations=1, warmup_rounds=1)
    assert summaries and "OCR excerpt" in summaries[0]
