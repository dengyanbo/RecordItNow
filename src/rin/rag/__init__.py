"""RAG search agent.

* :class:`Embedder`    — wraps ``sentence-transformers`` with a CPU model
  cached to ``%LOCALAPPDATA%\\RIN\\models``.
* :func:`index_capture` — embed an analyzed capture and upsert into ChromaDB.
* :func:`search`       — vector + metadata-filtered query.
* :class:`RAGAgent`    — retrieval-augmented Q&A using the active LLM provider.
"""
from __future__ import annotations

from .agent import RAGAgent
from .embedder import DEFAULT_MODEL, Embedder, get_embedder
from .indexer import index_capture, index_pending
from .search import SearchHit, search

__all__ = [
    "DEFAULT_MODEL",
    "Embedder",
    "RAGAgent",
    "SearchHit",
    "get_embedder",
    "index_capture",
    "index_pending",
    "search",
]
