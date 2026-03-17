"""Qdrant connection management — singleton client with health checks and graceful fallback."""

import logging

from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_GRPC_PORT = 6334

_client: QdrantClient | None = None
_available: bool | None = None  # None = not checked yet


def get_client() -> QdrantClient | None:
    """Get or create Qdrant client singleton. Returns None if unavailable."""
    global _client, _available

    if _available is False:
        return None

    if _client is not None:
        return _client

    try:
        _client = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            grpc_port=QDRANT_GRPC_PORT,
            prefer_grpc=False,  # REST for simplicity, switch to gRPC for perf later
            timeout=10,
        )
        # Health check
        _client.get_collections()
        _available = True
        logger.info("Qdrant client connected at %s:%s", QDRANT_HOST, QDRANT_PORT)
        return _client
    except Exception as e:
        logger.warning("Qdrant unavailable: %s — search will use legacy fallback", e)
        _available = False
        _client = None
        return None


def is_available() -> bool:
    """Check if Qdrant is reachable."""
    global _available
    if _available is None:
        get_client()
    return _available or False


def reset():
    """Reset client state — used for reconnection attempts."""
    global _client, _available
    if _client:
        try:
            _client.close()
        except Exception:  # noqa: S110
            pass
    _client = None
    _available = None


def health_check() -> dict:
    """Return health status for Sentinel integration."""
    try:
        client = get_client()
        if client is None:
            return {"status": "unavailable", "error": "client not connected"}
        collections = client.get_collections()
        return {
            "status": "healthy",
            "collections": len(collections.collections),
            "host": f"{QDRANT_HOST}:{QDRANT_PORT}",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
