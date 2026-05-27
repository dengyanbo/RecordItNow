"""Image analyzer composition tests."""
from __future__ import annotations

from pathlib import Path

from rin.analysis import image_analyzer, ocr
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities


class _NoVisionProvider(Provider):
    name = "fake-novision"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        raise AssertionError("vision shouldn't be called")

    def analyze_text(self, prompt, *, system=None):
        return "ok"

    def chat(self, messages):
        return "ok"


class _VisionProvider(Provider):
    name = "fake-vision"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=True, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="A code editor showing main.py", text="main.py")

    def analyze_text(self, prompt, *, system=None):
        return "ok"

    def chat(self, messages):
        return "ok"


def test_uses_vision_provider_when_available(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    monkeypatch.setattr("rin.analysis.image_analyzer.extract_text", lambda _p: "")
    result = image_analyzer.analyze_image(img, provider=_VisionProvider())
    assert "code editor" in result.summary
    assert result.text == "main.py"


def test_fallback_uses_ocr_text_when_no_vision(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    monkeypatch.setattr(
        "rin.analysis.image_analyzer.extract_text", lambda _p: "Line one\nLine two"
    )
    result = image_analyzer.analyze_image(img, provider=_NoVisionProvider())
    assert "OCR excerpt" in result.summary
    assert "Line one" in result.summary
    assert "Line one" in result.text


def test_works_without_any_provider(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    monkeypatch.setattr("rin.analysis.image_analyzer.extract_text", lambda _p: "")
    result = image_analyzer.analyze_image(img, provider=None)
    assert "Screenshot captured" in result.summary
    assert result.text == ""
    ocr.reset_engine()
