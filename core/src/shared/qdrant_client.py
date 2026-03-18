"""Qdrant connection management — singleton client with health checks and graceful fallback."""

import logging
import time

from qdrant_client import AsyncQdrantClient

logger = logging.getLogger(__name__)

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_GRPC_PORT = 6334
_RETRY_INTERVAL = 5  # seconds before retrying after failure

_client: AsyncQdrantClient | None = None
_available: bool | None = None  # None = not checked yet
_last_failure: float = 0


async def get_client() -> AsyncQdrantClient | None:
    """Get or create Qdrant client singleton. Returns None if unavailable."""
    global _client, _available, _last_failure

    if _available is False:
        # Retry after interval
        if time.monotonic() - _last_failure < _RETRY_INTERVAL:
            return None
        # Reset and try again
        _available = None
        _client = None

    if _client is not None:
        return _client

    try:
        _client = AsyncQdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            grpc_port=QDRANT_GRPC_PORT,
            prefer_grpc=True,
            timeout=10,
        )
        # Health check
        await _client.get_collections()
        _available = True
        logger.info("Qdrant client connected at %s:%s", QDRANT_HOST, QDRANT_PORT)
        return _client
    except Exception as e:
        logger.warning("Qdrant unavailable: %s — will retry in %ds", e, _RETRY_INTERVAL)
        _available = False
        _last_failure = time.monotonic()
        _client = None
        return None


async def is_available() -> bool:
    """Check if Qdrant is reachable."""
    global _available
    if _available is None:
        await get_client()
    return _available or False


async def reset():
    """Reset client state — used for reconnection attempts."""
    global _client, _available
    if _client:
        try:
            await _client.close()
        except Exception:  # noqa: S110
            pass
    _client = None
    _available = None


async def health_check() -> dict:
    """Return health status for Sentinel integration."""
    try:
        client = await get_client()
        if client is None:
            return {"status": "unavailable", "error": "client not connected"}
        collections = await client.get_collections()
        return {
            "status": "healthy",
            "collections": len(collections.collections),
            "host": f"{QDRANT_HOST}:{QDRANT_PORT}",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
