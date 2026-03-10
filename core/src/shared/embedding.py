"""Shared embedding service — MLX-native Qwen3-Embedding via oMLX bridge.

Primary: mlx-embeddings Qwen3-Embedding-0.6B (1024d) via persistent subprocess worker.
Graceful degradation: returns None when oMLX worker is unavailable.
Used by memvault, intelflow, and briefing modules for pgvector semantic search.

Redis cache layer intercepts before omlx_bridge to avoid Lock contention
under concurrent load (see embedding_cache.py for key format and TTL).
"""

import logging

from . import embedding_cache, omlx_bridge
from .chunking import ChunkingStrategy, FixedLengthChunking

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B output dimension


async def get_embedding(text: str, task_type: str | None = None) -> list[float] | None:
    """Generate embedding vector via oMLX bridge with Redis cache.

    Args:
        text: The text to embed.
        task_type: Optional prefix for task-aware models.
                   Supported: "search_query", "search_document", "clustering", "classification"

    Returns None if oMLX is unavailable (graceful degradation).
    """
    cached = await embedding_cache.get_cached(text, task_type)
    if cached is not None:
        return cached

    result = await omlx_bridge.embed_single(text, task_type=task_type)
    if result is not None:
        await embedding_cache.set_cached(text, result, task_type)
    return result


async def get_embeddings_batch(
    texts: list[str],
    task_type: str | None = None,
) -> list[list[float] | None]:
    """Generate embeddings for multiple texts with batch cache lookup."""
    if not texts:
        return []

    # Batch cache lookup
    cached = await embedding_cache.get_cached_batch(texts, task_type)

    # Identify misses
    miss_indices = [i for i, v in enumerate(cached) if v is None]
    if not miss_indices:
        return cached  # All hits

    # Compute only misses
    miss_texts = [texts[i] for i in miss_indices]
    computed = await omlx_bridge.embed_texts(miss_texts, task_type=task_type)

    # Merge results and store computed vectors
    results = list(cached)
    store_texts: list[str] = []
    store_vectors: list[list[float] | None] = []
    for idx, vec in zip(miss_indices, computed, strict=True):
        results[idx] = vec
        store_texts.append(texts[idx])
        store_vectors.append(vec)

    await embedding_cache.set_cached_batch(store_texts, store_vectors, task_type)
    return results


async def get_embeddings_chunked(
    text: str,
    *,
    max_chunk_chars: int = 2000,
    overlap: int = 200,
    strategy: ChunkingStrategy | None = None,
) -> list[dict]:
    """Chunk text and embed each chunk separately.

    Returns list of {chunk: str, embedding: list[float], index: int}.
    For short texts (< max_chunk_chars), returns a single chunk.
    """
    if len(text) < max_chunk_chars:
        chunks = [text]
    else:
        chunker = strategy or FixedLengthChunking(chunk_size=max_chunk_chars, overlap=overlap)
        chunks = chunker.chunk(text)

    embeddings = await get_embeddings_batch(chunks)
    return [
        {"chunk": chunk, "embedding": emb, "index": i}
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True))
        if emb is not None
    ]
