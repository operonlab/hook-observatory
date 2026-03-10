"""Shared embedding service — MLX-native Qwen3-Embedding via oMLX bridge.

Primary: mlx-embeddings Qwen3-Embedding-0.6B (1024d) via persistent subprocess worker.
Graceful degradation: returns None when oMLX worker is unavailable.
Used by memvault, intelflow, and briefing modules for pgvector semantic search.
"""

import logging

from . import omlx_bridge
from .chunking import ChunkingStrategy, FixedLengthChunking

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B output dimension


async def get_embedding(text: str, task_type: str | None = None) -> list[float] | None:
    """Generate embedding vector via oMLX bridge.

    Args:
        text: The text to embed.
        task_type: Optional prefix for task-aware models.
                   Supported: "search_query", "search_document", "clustering", "classification"

    Returns None if oMLX is unavailable (graceful degradation).
    """
    return await omlx_bridge.embed_single(text, task_type=task_type)


async def get_embeddings_batch(
    texts: list[str],
    task_type: str | None = None,
) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in a single call."""
    return await omlx_bridge.embed_texts(texts, task_type=task_type)


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
