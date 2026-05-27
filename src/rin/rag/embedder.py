"""Sentence-transformer embedder.

Wraps :class:`sentence_transformers.SentenceTransformer` so the rest of
the codebase doesn't pay the import cost unless RAG is actually used.

The model is loaded lazily and cached at module scope; subsequent calls
to :func:`get_embedder` return the same instance.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence

from ..paths import models_cache_dir
from ..utils.logging import get_logger

log = get_logger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


class Embedder:
    """Tiny wrapper around ``SentenceTransformer`` for a single model name."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def dim(self) -> int:
        return self._get_model().get_sentence_embedding_dimension()

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("sentence-transformers not installed") from exc
        cache_dir = models_cache_dir() / "sentence-transformers"
        cache_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Loading sentence-transformer model {self.model_name!r}…")
        self._model = SentenceTransformer(self.model_name, cache_folder=str(cache_dir))
        return self._model

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]


def get_embedder(model_name: str = DEFAULT_MODEL) -> Embedder:
    """Module-level singleton accessor."""

    global _embedder
    if _embedder is not None and _embedder.model_name == model_name:
        return _embedder
    with _embedder_lock:
        if _embedder is None or _embedder.model_name != model_name:
            _embedder = Embedder(model_name)
        return _embedder


def reset() -> None:
    """Drop the cached embedder. Tests use this to swap mocks."""

    global _embedder
    _embedder = None
