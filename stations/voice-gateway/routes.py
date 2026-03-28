"""HTTP routes for Voice Gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict

import httpx
from fastapi import APIRouter, Request
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
    from state_machine import GatewayState

    body = await request.json()
    event_type = body.get("type", "")
    payload = body.get("payload", {})
    payload["source_path"] = "client"

    app = request.app
    arbiter = app.state.arbiter
    sm = app.state.state_machine

    # Handle lifecycle events
    if event_type == "voice.client.connected":
        arbiter.client_connect()
    elif event_type == "voice.client.disconnected":
        arbiter.client_disconnect(reason=payload.get("reason", "explicit"))
    elif event_type == "voice.client.heartbeat":
        arbiter.client_heartbeat()
        return {"ok": True}

    # Drive state machine from client events
    if event_type == "voice.wakeword.detected":
        if sm.state in (GatewayState.IDLE, GatewayState.LISTENING):
            sm.transition(GatewayState.PROCESSING, reason="client_kws_match")
    elif event_type == "voice.speech.captured":
        if sm.state == GatewayState.PROCESSING:
            sm.transition(GatewayState.RESPONDING, reason="client_speech_complete")
    elif event_type == "voice.transcript.completed":
        sm.reset()  # back to IDLE

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
                except TimeoutError:
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


# ── STT proxy routes ──

_STT_BASE = "http://127.0.0.1:10200"


@router.get("/api/stt/health")
async def stt_health():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{_STT_BASE}/health")
            return r.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@router.get("/api/stt/engines")
async def stt_engines():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{_STT_BASE}/engines")
            return r.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


# ── Metrics + devices ──


@router.get("/api/voice/metrics")
async def voice_metrics(request: Request):
    """Real-time pipeline metrics (updated every tick by pipeline loop)."""
    return request.app.state.metrics or {}


@router.get("/api/voice/devices")
async def voice_devices():
    """List available audio input devices."""
    import sounddevice as sd

    devices = []
    try:
        default_idx = sd.default.device[0]
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": d["name"],
                        "channels": d["max_input_channels"],
                        "sample_rate": int(d["default_samplerate"]),
                        "is_default": i == default_idx,
                    }
                )
    except Exception as e:
        return {"devices": [], "error": str(e)}
    return {"devices": devices}


@router.post("/api/voice/transcribe")
async def transcribe_audio(request: Request):
    """Receive audio from client browser, forward to STT station for transcription."""
    import tempfile
    from pathlib import Path

    body = await request.body()
    if not body:
        return {"error": "empty body"}

    cfg = request.app.state.config

    # Save to temp WAV file
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(body)
    tmp.close()

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{_STT_BASE}/transcribe",
                params={
                    "path": tmp.name,
                    "language": cfg.language,
                    "engine": cfg.server.stt_engine,
                },
            )
            result = r.json()

        # Publish transcript event
        text = result.get("text", "").strip()
        if text:
            event_bus = request.app.state.event_bus
            payload = {
                "text": text,
                "language": cfg.language,
                "engine": result.get("engine", cfg.server.stt_engine),
                "source_path": "client",
            }
            if event_bus:
                await event_bus.publish("voice.transcript.completed", payload)
            sse_broadcast({"type": "voice.transcript.completed", **payload, "ts": time.time()})

            # Reset state machine
            request.app.state.state_machine.reset()

        return result
    except Exception as e:
        logger.error("transcribe_failed: %s", e)
        return {"error": str(e)}
    finally:
        Path(tmp.name).unlink(missing_ok=True)
