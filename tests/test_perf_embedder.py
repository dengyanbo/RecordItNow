"""Benchmark embed_batch(10) overhead (target: ≤500ms with a mocked model)."""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("pytest_benchmark")

from rin.rag import embedder


class _FakeVector:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeSTModel:
    def __init__(self, _name: str, **_kwargs) -> None:
        pass

    def get_sentence_embedding_dimension(self) -> int:
        return 16

    def encode(self, texts, *, normalize_embeddings: bool = True, show_progress_bar: bool = False):
        return [
            _FakeVector([float(index + offset) for offset in range(16)])
            for index, _text in enumerate(texts)
        ]


@pytest.fixture(autouse=True)
def patch_model(monkeypatch: pytest.MonkeyPatch):
    embedder.reset()
    fake_mod = type(sys)("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeSTModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
    yield
    embedder.reset()


@pytest.mark.benchmark(group="embedder")
def test_embed_batch_benchmark(benchmark) -> None:
    """target: ≤500ms for embed_batch(10) with a mocked SentenceTransformer."""

    instance = embedder.get_embedder("fake-model")
    instance.embed_batch(["warmup"])
    texts = [f"text-{index}" for index in range(10)]
    batch_sizes: list[int] = []

    def run_embed() -> int:
        vectors = instance.embed_batch(texts)
        batch_sizes[:] = [len(vectors)]
        return len(vectors)

    benchmark.pedantic(run_embed, rounds=10, iterations=1, warmup_rounds=1)
    assert batch_sizes == [10]
