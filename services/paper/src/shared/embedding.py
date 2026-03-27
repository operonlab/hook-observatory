"""Embedding stub for paper-svc — returns None (keyword fallback).

paper-svc runs without MLX embed_worker. All semantic search falls back to ILIKE text search.
"""


async def get_embedding(text: str, task_type: str | None = None) -> list[float] | None:
    """Paper-svc runs without MLX — always returns None for keyword fallback."""
    return None
