"""Agent-Metrics SSE endpoint — single stream replacing 5 setInterval polls."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent_metrics.sse import register_client, unregister_client

router = APIRouter()


@router.get("/events/stream")
async def sse_events(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for real-time dashboard updates.

    Events emitted:
      - connected  : initial handshake (empty data)
      - system     : CPU/MEM/NET/DISK snapshot (every ~5s from sysmon_loop)
      - sessions   : active session list (every ~10s from aggregator)
      - quota      : LLM quota data (every ~60s from sysmon_loop quota merge)
      - usage      : budget/trends (every ~60s from aggregator)
      - operations : maestro runs (every ~30s from dispatch saves)
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    register_client(queue)

    async def generate():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unregister_client(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
