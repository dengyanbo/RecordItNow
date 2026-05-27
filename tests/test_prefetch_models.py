"""Tests for scripts/prefetch_models.py — patches every loader."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the script as a module so we can patch its symbols.
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prefetch_models.py"


@pytest.fixture
def prefetch_mod():
    spec = importlib.util.spec_from_file_location("prefetch_models", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prefetch_models"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("prefetch_models", None)


def test_main_invokes_each_loader(prefetch_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(prefetch_mod, "prefetch_sentence_transformer", lambda: called.append("st"))
    monkeypatch.setattr(prefetch_mod, "prefetch_rapidocr", lambda: called.append("ocr"))
    monkeypatch.setattr(prefetch_mod, "prefetch_whisper", lambda name: called.append(f"whisper:{name}"))

    rc = prefetch_mod.main(["--whisper", "tiny"])
    assert rc == 0
    assert called == ["st", "ocr", "whisper:tiny"]


def test_main_skip_flag_omits_loader(prefetch_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(prefetch_mod, "prefetch_sentence_transformer", lambda: called.append("st"))
    monkeypatch.setattr(prefetch_mod, "prefetch_rapidocr", lambda: called.append("ocr"))
    monkeypatch.setattr(prefetch_mod, "prefetch_whisper", lambda name: called.append("whisper"))

    rc = prefetch_mod.main(["--skip", "whisper", "--skip", "ocr"])
    assert rc == 0
    assert called == ["st"]


def test_main_returns_nonzero_when_loader_fails(
    prefetch_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom():
        raise RuntimeError("no internet")

    monkeypatch.setattr(prefetch_mod, "prefetch_sentence_transformer", boom)
    monkeypatch.setattr(prefetch_mod, "prefetch_rapidocr", lambda: None)
    monkeypatch.setattr(prefetch_mod, "prefetch_whisper", lambda name: None)

    rc = prefetch_mod.main(["--whisper", "tiny"])
    assert rc == 1  # partial failure


def test_main_all_fail_returns_nonzero(prefetch_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(prefetch_mod, "prefetch_sentence_transformer", boom)
    monkeypatch.setattr(prefetch_mod, "prefetch_rapidocr", boom)
    monkeypatch.setattr(prefetch_mod, "prefetch_whisper", lambda name: boom())

    rc = prefetch_mod.main([])
    assert rc == 1
