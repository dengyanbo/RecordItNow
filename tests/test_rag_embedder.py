"""Embedder tests with a stubbed sentence-transformers model."""
from __future__ import annotations

import pytest

from rin.rag import embedder


class _FakeSTModel:
    def __init__(self, _name: str, **_kwargs) -> None:
        pass

    def get_sentence_embedding_dimension(self) -> int:
        return 16

    def encode(self, texts, *, normalize_embeddings: bool = True, show_progress_bar: bool = False):
        import numpy as np

        rng = np.random.default_rng(seed=42)
        return rng.standard_normal((len(texts), 16))


@pytest.fixture(autouse=True)
def _patch_model(monkeypatch: pytest.MonkeyPatch):
    embedder.reset()

    # Patch the import inside _get_model — simulate sentence_transformers.SentenceTransformer.
    import sys

    fake_mod = type(sys)("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeSTModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
    yield
    embedder.reset()


def test_embed_returns_vector_of_expected_dim() -> None:
    e = embedder.get_embedder("fake-model")
    vec = e.embed("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 16


def test_embed_batch_returns_one_per_input() -> None:
    e = embedder.get_embedder("fake-model")
    vecs = e.embed_batch(["a", "b", "c"])
    assert len(vecs) == 3
    assert all(len(v) == 16 for v in vecs)


def test_empty_batch_returns_empty_list() -> None:
    e = embedder.get_embedder("fake-model")
    assert e.embed_batch([]) == []


def test_get_embedder_singleton_per_model_name() -> None:
    a = embedder.get_embedder("fake-model")
    b = embedder.get_embedder("fake-model")
    assert a is b
    c = embedder.get_embedder("other-model")
    assert c is not a
