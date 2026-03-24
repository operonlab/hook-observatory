"""HTTP routes for Voice Gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# SSE client queues
_sse_clients: list[asyncio.Queue] = []


def sse_broadcast(event: dict) -> None:
    """Push event to all connected SSE clients."""
    data = json.dumps(event, ensure_ascii=False)
    for q in _sse_clients:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


@router.get("/health")
async def health(request: Request):
    app = request.app
    sm = app.state.state_machine
    arbiter = app.state.arbiter
    return {
        "status": "ok",
        "port": app.state.config.port,
        **sm.status(),
        "mode": arbiter.active_mode.value,
    }


@router.get("/status")
async def status(request: Request):
    app = request.app
    sm = app.state.state_machine
    arbiter = app.state.arbiter
    events = app.state.event_bus
    return {
        **sm.status(),
        **arbiter.status(),
        "events_published": events.event_count if events else 0,
        "pipeline_active": app.state.pipeline_active,
    }


@router.get("/api/voice/config")
async def get_client_config(request: Request):
    """Return config suitable for client-side web-asr-core."""
    cfg = request.app.state.config
    return {
        "language": cfg.language,
        "keywords": cfg.keywords,
        "sensitivity": cfg.sensitivity,
        "client": asdict(cfg.client),
    }


@router.post("/api/voice/events")
async def receive_client_event(request: Request):
    """Receive voice events from browser (Path A).

    Expected body: {"type": "voice.*", "payload": {...}}
    """
    body = await request.json()
    event_type = body.get("type", "")
    payload = body.get("payload", {})
    payload["source_path"] = "client"

    app = request.app
    arbiter = app.state.arbiter

    # Handle lifecycle events
    if event_type == "voice.client.connected":
        arbiter.client_connect()
    elif event_type == "voice.client.disconnected":
        arbiter.client_disconnect(reason=payload.get("reason", "explicit"))
    elif event_type == "voice.client.heartbeat":
        arbiter.client_heartbeat()
        return {"ok": True}

    # Forward to Redis
    event_bus = app.state.event_bus
    if event_bus:
        await event_bus.publish(event_type, payload)

    # SSE fanout
    sse_broadcast({"type": event_type, **payload, "ts": time.time()})

    return {"ok": True}


@router.post("/api/voice/mode")
async def set_mode(request: Request):
    """Manual mode override. Body: {"mode": "server"|"client"|"standby"|null}"""
    from arbiter import VoiceMode

    body = await request.json()
    mode_str = body.get("mode")
    arbiter = request.app.state.arbiter

    if mode_str is None:
        mode = arbiter.set_override(None)
    else:
        mode = arbiter.set_override(VoiceMode(mode_str))

    return {"active_mode": mode.value}


@router.get("/api/voice/stream")
async def sse_stream(request: Request):
    """SSE endpoint for real-time voice events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.append(q)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'ts': time.time()})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _sse_clients.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
