"""Shared embedding service — Ollama nomic-embed-text integration.

Used by memvault and intelflow modules for pgvector semantic search.
Graceful degradation: returns None when Ollama is unavailable.
Retry with exponential backoff on transient errors (429, 503, timeouts).
"""

import asyncio
import logging

import httpx

from .chunking import ChunkingStrategy, FixedLengthChunking

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768  # nomic-embed-text output dimension

# Retry config
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds — exponential: 1s, 2s, 4s
RETRYABLE_STATUS = {429, 503, 502}

_client: httpx.AsyncClient | None = None
_semaphore = asyncio.Semaphore(4)  # limit concurrent Ollama calls


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _is_retryable(exc: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRYABLE_STATUS:
        return True
    return False


async def _post_with_retry(payload: dict) -> httpx.Response:
    """POST to Ollama /api/embed with retry + exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with _semaphore:
                resp = await _get_client().post(
                    f"{OLLAMA_URL}/api/embed",
                    json=payload,
                )
                resp.raise_for_status()
                return resp
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            if not _is_retryable(e) or attempt == MAX_RETRIES:
                raise
            last_exc = e
            delay = RETRY_BASE_DELAY * (2**attempt)
            logger.warning(
                "Ollama request failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def get_embedding(text: str, task_type: str | None = None) -> list[float] | None:
    """Generate embedding vector for text via Ollama.

    Args:
        text: The text to embed.
        task_type: Optional prefix for task-aware models.
                   Supported: "search_query", "search_document", "clustering", "classification"
                   When set, prepends "{task_type}: " to the text.

    Returns None if Ollama is unavailable (graceful degradation).
    """
    prefixed = f"{task_type}: {text}" if task_type else text
    try:
        resp = await _post_with_retry({"model": MODEL, "input": prefixed})
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if embeddings and len(embeddings[0]) == EMBEDDING_DIM:
            return embeddings[0]
        logger.warning("Unexpected embedding dim: %d", len(embeddings[0]) if embeddings else 0)
        return None
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


async def get_embeddings_batch(
    texts: list[str],
    task_type: str | None = None,
) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in a single call.

    Args:
        texts: The texts to embed.
        task_type: Optional prefix for task-aware models.
                   When set, prepends "{task_type}: " to each text.
    """
    prefixed = [f"{task_type}: {t}" if task_type else t for t in texts]
    try:
        resp = await _post_with_retry({"model": MODEL, "input": prefixed})
        data = resp.json()
        embeddings = data.get("embeddings", [])
        results: list[list[float] | None] = []
        for i, _text in enumerate(texts):
            if i < len(embeddings) and len(embeddings[i]) == EMBEDDING_DIM:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Batch embedding failed: %s", e)
        return [None] * len(texts)


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
