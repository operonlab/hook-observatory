"""Agent-Metrics SSE broadcast module — decoupled to avoid circular imports."""

from __future__ import annotations

import asyncio
import json

# Set of active SSE client queues
_sse_clients: set[asyncio.Queue] = set()


async def sse_broadcast(event_type: str, data: dict) -> None:
    """Broadcast an event to all connected SSE clients."""
    payload = json.dumps(data, default=str)
    message = f"event: {event_type}\ndata: {payload}\n\n"
    dead: set[asyncio.Queue] = set()
    for q in _sse_clients:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_clients.difference_update(dead)


def register_client(queue: asyncio.Queue) -> None:
    _sse_clients.add(queue)


def unregister_client(queue: asyncio.Queue) -> None:
    _sse_clients.discard(queue)
