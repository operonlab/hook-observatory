"""Embedding service — Ollama nomic-embed-text integration.

Graceful degradation: returns None when Ollama is unavailable.
Reuses pattern from core/src/shared/embedding.py but sync (CLI tool).
"""

from __future__ import annotations

import structlog
import httpx

logger = structlog.get_logger(__name__)


def get_embedding(text: str, ollama_url: str = "http://localhost:11434",
                  model: str = "nomic-embed-text", dim: int = 768) -> list[float] | None:
    """Generate embedding vector for text via Ollama.

    Returns None if Ollama is unavailable (graceful degradation).
    """
    try:
        resp = httpx.post(
            f"{ollama_url}/api/embed",
            json={"model": model, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if embeddings and len(embeddings[0]) == dim:
            return embeddings[0]
        logger.warning("unexpected_embedding_dim", expected=dim,
                       actual=len(embeddings[0]) if embeddings else 0)
        return None
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("embedding_failed", error=str(e))
        return None


def get_embeddings_batch(texts: list[str], ollama_url: str = "http://localhost:11434",
                         model: str = "nomic-embed-text", dim: int = 768) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in a single call."""
    try:
        resp = httpx.post(
            f"{ollama_url}/api/embed",
            json={"model": model, "input": texts},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        results: list[list[float] | None] = []
        for i in range(len(texts)):
            if i < len(embeddings) and len(embeddings[i]) == dim:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("batch_embedding_failed", error=str(e))
        return [None] * len(texts)
