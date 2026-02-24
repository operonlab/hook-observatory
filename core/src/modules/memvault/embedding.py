"""Embedding service — Ollama nomic-embed-text integration.

Local module utility (not shared) per shared code threshold.
"""

import logging

import httpx

from .models import EMBEDDING_DIM

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
MODEL = "nomic-embed-text"
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def get_embedding(text: str) -> list[float] | None:
    """Generate embedding vector for text via Ollama.

    Returns None if Ollama is unavailable (graceful degradation).
    """
    try:
        resp = await _get_client().post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": MODEL, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if embeddings and len(embeddings[0]) == EMBEDDING_DIM:
            return embeddings[0]
        logger.warning("Unexpected embedding dim: %d", len(embeddings[0]) if embeddings else 0)
        return None
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


async def get_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in a single call."""
    try:
        resp = await _get_client().post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": MODEL, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        results: list[list[float] | None] = []
        for i, text in enumerate(texts):
            if i < len(embeddings) and len(embeddings[i]) == EMBEDDING_DIM:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Batch embedding failed: %s", e)
        return [None] * len(texts)
