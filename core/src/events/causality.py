"""Causality chain tracking for EventBus.

Provides a public API for reading/setting correlation context and
querying causal chains stored in Redis.

Design: "Structured first, AI guess last" — explicitly track causality
in the event system itself rather than inferring relationships after
the fact.

Usage:
    # Reading context (inside an event handler):
    from src.events.causality import get_correlation_id, get_causation_id
    corr_id = get_correlation_id()   # shared chain ID
    cause_id = get_causation_id()    # event that triggered this handler

    # Setting context (e.g., from an HTTP request header):
    from src.events.causality import set_correlation_id
    set_correlation_id(request.headers.get("X-Correlation-ID"))

    # Querying a chain (diagnostics / debugging):
    from src.events.causality import record_event, get_causality_chain
    chain = await get_causality_chain(corr_id)
"""

from __future__ import annotations

import json
import uuid

import structlog

from src.events.backends.base import _causation_id, _correlation_id

logger = structlog.get_logger()

# Redis key prefix and TTL for causality chain storage
_CHAIN_PREFIX = "event:chain:"
_CHAIN_TTL_SECONDS = 3600  # 1 hour


# ------------------------------------------------------------------ context accessors


def get_correlation_id() -> str | None:
    """Get current correlation ID from ContextVar.

    Returns the correlation_id of the event chain currently being
    processed, or None if outside an event handler.
    """
    return _correlation_id.get(None)


def get_causation_id() -> str | None:
    """Get current causation ID from ContextVar.

    Returns the event.id of the event that triggered the currently
    executing handler, or None if outside an event handler.
    """
    return _causation_id.get(None)


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set correlation ID in ContextVar for the current async context.

    Useful for propagating a correlation ID from an HTTP request header
    (e.g., ``X-Correlation-ID``) into the EventBus context so that any
    events published during request handling share the same chain.

    Args:
        correlation_id: The correlation ID to set. If None, generates a new UUID.

    Returns:
        The correlation ID that was set.
    """
    cid = correlation_id or uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def new_correlation_id() -> str:
    """Generate and set a fresh correlation ID. Returns the new ID."""
    return set_correlation_id(uuid.uuid4().hex)


# ------------------------------------------------------------------ chain storage (Redis)


async def record_event(redis, event) -> None:
    """Append an event summary to its correlation chain in Redis.

    Call this from middleware or after publish to build a queryable
    chain of all events sharing the same ``correlation_id``.

    Args:
        redis: An async Redis client (``redis.asyncio``).
        event: An ``Event`` instance.
    """
    if redis is None:
        return

    key = _CHAIN_PREFIX + event.correlation_id
    entry = json.dumps(
        {
            "event_id": event.id,
            "type": event.type,
            "source": event.source,
            "causation_id": event.causation_id,
            "timestamp": event.timestamp.isoformat(),
        }
    )

    try:
        pipe = redis.pipeline()
        pipe.rpush(key, entry)
        pipe.expire(key, _CHAIN_TTL_SECONDS)
        await pipe.execute()
    except Exception as e:
        # Non-critical — chain recording failure must not break event flow
        logger.warning("causality_record_failed", correlation_id=event.correlation_id, error=str(e))


async def get_causality_chain(redis, correlation_id: str) -> list[dict]:
    """Retrieve the full chain of events for a correlation ID.

    Args:
        redis: An async Redis client (``redis.asyncio``).
        correlation_id: The correlation ID to query.

    Returns:
        A list of event summaries in chronological order, each containing:
        ``event_id``, ``type``, ``source``, ``causation_id``, ``timestamp``.
        Returns an empty list if redis is None or the chain is not found.
    """
    if redis is None:
        return []

    key = _CHAIN_PREFIX + correlation_id
    try:
        raw_entries = await redis.lrange(key, 0, -1)
        return [json.loads(entry) for entry in raw_entries]
    except Exception as e:
        logger.warning("causality_chain_read_failed", correlation_id=correlation_id, error=str(e))
        return []
