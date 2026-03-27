"""Qdrant client stub for paper-svc — always returns unavailable."""


async def is_available() -> bool:
    """paper-svc does not connect to Qdrant — always falls back to ILIKE search."""
    return False
