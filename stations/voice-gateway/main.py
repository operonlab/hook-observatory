"""Voice Gateway — dual-path voice trigger/router station."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from workshop.station_bootstrap import setup_logging

from arbiter import ModeArbiter
from config import config
from events import VoiceEventBus
from routes import router, sse_broadcast
from state_machine import GatewayState, StateMachine

logger = setup_logging("voice-gateway")

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
_MODELS_DIR = Path(__file__).parent / "models"


def _resolve_model_path(rel: str) -> Path:
    """Resolve model path relative to station directory."""
    p = Path(rel)
    if p.is_absolute():
        return p
    return Path(__file__).parent / p


async def _pipeline_loop(app_state) -> None:
    """Main server-side pipeline loop (Path B).

    Runs: AudioSource → VAD → (future: KWS) → STT Bridge → Events
    """
    from pipeline.audio_source import AudioSource
    from pipeline.stt_bridge import STTBridge
    from pipeline.vad import VadGate

    sm: StateMachine = app_state.state_machine
    arbiter: ModeArbiter = app_state.arbiter
    event_bus: VoiceEventBus | None = app_state.event_bus

    # Initialize operators
    vad_model = _resolve_model_path(config.server.vad_model)
    if not vad_model.exists():
        logger.error("vad_model_not_found: %s — run scripts/download_models.py", vad_model)
        return

    audio = AudioSource(
        sample_rate=config.server.sample_rate,
        chunk_ms=config.server.chunk_ms,
    )
    vad = VadGate(
        model_path=vad_model,
        sample_rate=config.server.sample_rate,
        threshold=config.server.vad_threshold,
    )
    stt = STTBridge(
        ws_url=config.server.stt_ws_url,
        engine=config.server.stt_engine,
        language=config.language,
    )

    speech_buffer: list[np.ndarray] = []
    last_speech_time = 0.0
    chunk_duration_s = config.server.chunk_ms / 1000.0

    try:
        await audio.start()
        app_state.pipeline_active = True
        logger.info("pipeline_started")

        while True:
            # Check if server should be capturing
            if not arbiter.server_should_capture:
                if audio.active:
                    audio.pause()
                await asyncio.sleep(1)
                continue
            elif not audio.active:
                audio.resume()

            chunk = await audio.read_chunk()
            now = time.monotonic()

            is_speech = vad.accept(chunk)

            # ── IDLE: wait for speech ──
            if sm.state == GatewayState.IDLE:
                if is_speech:
                    sm.transition(GatewayState.PROCESSING, reason="vad_speech_detected")
                    speech_buffer = [chunk]
                    last_speech_time = now

                    if event_bus:
                        await event_bus.publish("voice.state.changed", {
                            "from": "IDLE",
                            "to": "PROCESSING",
                            "reason": "vad_speech_detected",
                            "source_path": "server",
                        })
                    sse_broadcast({
                        "type": "voice.state.changed",
                        "from": "IDLE", "to": "PROCESSING",
                    })

            # ── PROCESSING: accumulate speech, wait for silence ──
            elif sm.state == GatewayState.PROCESSING:
                speech_buffer.append(chunk)

                if is_speech:
                    last_speech_time = now
                else:
                    silence_duration = now - last_speech_time
                    speech_duration = len(speech_buffer) * chunk_duration_s

                    if (
                        silence_duration > config.processing_silence_s
                        and speech_duration > config.min_speech_for_stt_s
                    ):
                        # Speech ended — send to STT
                        full_audio = np.concatenate(speech_buffer)
                        audio_ms = int(len(full_audio) / config.server.sample_rate * 1000)

                        if event_bus:
                            await event_bus.publish("voice.speech.captured", {
                                "audio_duration_ms": audio_ms,
                                "source_path": "server",
                            })

                        logger.info("speech_captured: %d ms, sending to STT", audio_ms)

                        try:
                            result = await stt.transcribe(
                                full_audio,
                                sample_rate=config.server.sample_rate,
                            )
                            text = result.get("text", "").strip()
                            if text:
                                logger.info("transcript: %r", text[:80])
                                if event_bus:
                                    await event_bus.publish("voice.transcript.completed", {
                                        "text": text,
                                        "language": config.language,
                                        "engine": result.get("engine", config.server.stt_engine),
                                        "latency_ms": result.get("latency_ms", 0),
                                        "audio_duration_ms": audio_ms,
                                        "source_path": "server",
                                    })
                                sse_broadcast({
                                    "type": "voice.transcript.completed",
                                    "text": text,
                                })
                        except Exception as e:
                            logger.error("stt_failed: %s", e)
                            if event_bus:
                                await event_bus.publish("voice.error.occurred", {
                                    "error": "stt_failed",
                                    "detail": str(e),
                                    "state": "PROCESSING",
                                    "source_path": "server",
                                })

                        sm.reset()
                        speech_buffer = []

                # Timeout guard
                if sm.time_in_state() > config.processing_timeout_s:
                    logger.warning("processing_timeout: %.0fs", sm.time_in_state())
                    sm.reset()
                    speech_buffer = []

    except asyncio.CancelledError:
        logger.info("pipeline_cancelled")
    except Exception:
        logger.exception("pipeline_error")
    finally:
        await audio.stop()
        app_state.pipeline_active = False
        logger.info("pipeline_stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect Redis, start pipeline."""
    # State machine + arbiter
    app.state.config = config
    app.state.state_machine = StateMachine()
    app.state.arbiter = ModeArbiter(server_enabled=config.server.enabled)
    app.state.pipeline_active = False

    # Redis
    event_bus = None
    try:
        r = aioredis.from_url(config.redis_url, decode_responses=True, socket_connect_timeout=3)
        await r.ping()
        event_bus = VoiceEventBus(r, stream_prefix=config.stream_prefix)
        logger.info("redis_connected: %s", config.redis_url)
    except Exception:
        logger.warning("redis_unavailable — events will not be published")
        r = None

    app.state.redis = r
    app.state.event_bus = event_bus

    # Start server pipeline if enabled
    pipeline_task = None
    if config.server.enabled:
        pipeline_task = asyncio.create_task(_pipeline_loop(app.state))

    yield

    # Cleanup
    if pipeline_task:
        pipeline_task.cancel()
        await asyncio.gather(pipeline_task, return_exceptions=True)
    if r:
        await r.aclose()
    logger.info("shutdown_complete")


app = FastAPI(title="Voice Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        f"http://localhost:{config.port}",
        "https://workshop.joneshong.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    if _TEMPLATE_PATH.exists():
        return HTMLResponse(_TEMPLATE_PATH.read_text())
    return HTMLResponse("<h1>Voice Gateway</h1><p>Running on port {}</p>".format(config.port))


def cli():
    import uvicorn

    uvicorn.run(
        "main:app", host=config.host, port=config.port, reload=False, log_level="info"
    )


if __name__ == "__main__":
    cli()
