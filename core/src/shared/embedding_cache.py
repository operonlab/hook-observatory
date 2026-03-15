"""Embedding vector cache — Redis binary storage for oMLX embeddings.

Key format: emb:v1:{sha256(task_type:text)[:16]}
Value: struct.pack of float32 array (4096 bytes for 1024d)
TTL: 24 hours

All operations silently degrade when Redis is unavailable.
Bump version prefix (v1 → v2) when switching embedding models.
"""

import hashlib
import logging
import struct

from .redis import get_redis_binary

logger = logging.getLogger(__name__)

_VERSION = "v1"
_TTL = 86400  # 24 hours
_FMT_1024 = "1024f"  # struct format for 1024 floats
_PACK_SIZE = struct.calcsize(_FMT_1024)  # 4096 bytes


def _cache_key(text: str, task_type: str | None) -> str:
    """Generate cache key from text + task_type."""
    raw = f"{task_type or ''}:{text}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"emb:{_VERSION}:{digest}"


async def get_cached(text: str, task_type: str | None = None) -> list[float] | None:
    """Retrieve cached embedding vector. Returns None on miss or error."""
    try:
        r = get_redis_binary()
        data = await r.get(_cache_key(text, task_type))
        if data and len(data) == _PACK_SIZE:
            return list(struct.unpack(_FMT_1024, data))
    except Exception:
        logger.warning("embedding cache get failed", exc_info=True)
    return None


async def set_cached(text: str, vector: list[float], task_type: str | None = None) -> None:
    """Store embedding vector in cache."""
    try:
        r = get_redis_binary()
        packed = struct.pack(_FMT_1024, *vector)
        await r.set(_cache_key(text, task_type), packed, ex=_TTL)
    except Exception:
        logger.warning("embedding cache set failed", exc_info=True)


async def get_cached_batch(
    texts: list[str], task_type: str | None = None
) -> list[list[float] | None]:
    """Batch lookup via Redis pipeline. Returns list aligned with input."""
    results: list[list[float] | None] = [None] * len(texts)
    if not texts:
        return results
    try:
        r = get_redis_binary()
        keys = [_cache_key(t, task_type) for t in texts]
        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.get(k)
        raw_values = await pipe.execute()
        for i, data in enumerate(raw_values):
            if data and len(data) == _PACK_SIZE:
                results[i] = list(struct.unpack(_FMT_1024, data))
    except Exception:
        logger.warning("embedding cache batch get failed", exc_info=True)
    return results


async def set_cached_batch(
    texts: list[str],
    vectors: list[list[float] | None],
    task_type: str | None = None,
) -> None:
    """Batch store via Redis pipeline."""
    try:
        r = get_redis_binary()
        pipe = r.pipeline(transaction=False)
        for text, vec in zip(texts, vectors, strict=True):
            if vec is not None and len(vec) == 1024:
                packed = struct.pack(_FMT_1024, *vec)
                pipe.set(_cache_key(text, task_type), packed, ex=_TTL)
        await pipe.execute()
    except Exception:
        logger.warning("embedding cache batch set failed", exc_info=True)
