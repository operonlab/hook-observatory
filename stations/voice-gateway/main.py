"""Voice Gateway — dual-path voice trigger/router station."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import redis.asyncio as aioredis
from arbiter import ModeArbiter
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from state_machine import GatewayState, StateMachine

from config import config
from events import VoiceEventBus
from routes import router, sse_broadcast
from sdk_client.station_bootstrap import setup_logging

logger = setup_logging("voice-gateway", log_dir=Path("/opt/homebrew/var/log/workshop") / "voice-gateway", json=True)

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
_MODELS_DIR = Path(__file__).parent / "models"


def _resolve_model_path(rel: str) -> Path:
    """Resolve model path relative to station directory."""
    p = Path(rel)
    if p.is_absolute():
        return p
    return Path(__file__).parent / p


async def _publish(event_bus: VoiceEventBus | None, event_type: str, payload: dict) -> None:
    """Publish event to Redis + SSE."""
    if event_bus:
        await event_bus.publish(event_type, payload)
    sse_broadcast({"type": event_type, **payload})


async def _pipeline_loop(app_state) -> None:
    """Main server-side pipeline loop (Path B).

    Full pipeline: AudioSource → VAD → KWS → STT Bridge → Events
    State machine: IDLE → LISTENING → PROCESSING → RESPONDING → IDLE
    """
    from pipeline.audio_source import AudioSource
    from pipeline.kws import KeywordSpotter
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

    kws_model_dir = _resolve_model_path(config.server.kws_model_dir)
    kws_available = kws_model_dir.exists()
    if not kws_available:
        logger.warning("kws_model_not_found: %s — running without wake word", kws_model_dir)

    audio = AudioSource(
        sample_rate=config.server.sample_rate,
        chunk_ms=config.server.chunk_ms,
    )

    vad = VadGate(
        model_path=vad_model,
        sample_rate=config.server.sample_rate,
        threshold=config.server.vad_threshold,
    )
    kws = (
        KeywordSpotter(
            model_dir=kws_model_dir,
            keywords=config.keywords,
            sample_rate=config.server.sample_rate,
        )
        if kws_available
        else None
    )

    stt = STTBridge(
        ws_url=config.server.stt_ws_url,
        engine=config.server.stt_engine,
        language=config.language,
    )

    speech_buffer: list[np.ndarray] = []
    last_speech_time = 0.0
    chunk_duration_s = config.server.chunk_ms / 1000.0
    tick = 0
    max_peak = 0.0
    vad_emit_counter = 0  # throttle SSE for VAD/audio events

    try:
        await audio.start()
        app_state.pipeline_active = True
        logger.info("pipeline_started: kws=%s", "enabled" if kws else "disabled")

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
            tick += 1

            # Audio metrics
            peak = float(np.max(np.abs(chunk)))
            rms = float(np.sqrt(np.mean(chunk**2)))
            rms_db = 20 * np.log10(max(rms, 1e-10))
            if peak > max_peak:
                max_peak = peak

            is_speech = vad.accept(chunk)

            # Update shared metrics dict (consumed by /api/voice/metrics)
            speech_dur = len(speech_buffer) * chunk_duration_s
            silence_dur = now - last_speech_time if last_speech_time > 0 else 0
            app_state.metrics = {
                "audio": {"peak": round(peak, 4), "rms_db": round(rms_db, 1), "chunks": tick},
                "vad": {
                    "is_speech": is_speech,
                    "threshold": config.server.vad_threshold,
                    "speech_duration_s": round(speech_dur, 2),
                    "silence_duration_s": round(silence_dur, 2),
                },
                "kws": {"enabled": kws is not None, "keywords": config.keywords},
                "state": sm.status(),
            }

            # Throttled SSE: audio level every ~200ms (7 ticks at 30ms)
            vad_emit_counter += 1
            if vad_emit_counter >= 7:
                vad_emit_counter = 0
                sse_broadcast(
                    {
                        "type": "voice.audio.level",
                        "peak": round(peak, 4),
                        "rms_db": round(rms_db, 1),
                        "is_speech": is_speech,
                    }
                )

            # Periodic log (every ~3s)
            if tick % 100 == 0:
                logger.info("audio_level: peak=%.4f max=%.4f", peak, max_peak)
                max_peak = 0.0

            # ── IDLE: wait for speech (Tier 1 — VAD only) ──
            if sm.state == GatewayState.IDLE:
                if is_speech:
                    if kws:
                        # With KWS: go to LISTENING, run KWS
                        sm.transition(GatewayState.LISTENING, reason="vad_speech_detected")
                        speech_buffer = [chunk]
                        last_speech_time = now
                        await _publish(
                            event_bus,
                            "voice.state.changed",
                            {
                                "from": "IDLE",
                                "to": "LISTENING",
                                "reason": "vad_speech_detected",
                                "source_path": "server",
                            },
                        )
                    else:
                        # No KWS: skip directly to PROCESSING
                        sm.transition(GatewayState.PROCESSING, reason="vad_speech_detected")
                        speech_buffer = [chunk]
                        last_speech_time = now
                        await _publish(
                            event_bus,
                            "voice.state.changed",
                            {
                                "from": "IDLE",
                                "to": "PROCESSING",
                                "reason": "vad_speech_detected",
                                "source_path": "server",
                            },
                        )

            # ── LISTENING: VAD + KWS active (Tier 2) ──
            elif sm.state == GatewayState.LISTENING:
                speech_buffer.append(chunk)

                # KWS needs ALL chunks (speech + silence) for continuous decoding
                keyword = kws.accept(chunk) if kws else None
                if keyword:
                    sm.transition(GatewayState.PROCESSING, reason="kws_match")
                    await _publish(
                        event_bus,
                        "voice.wakeword.detected",
                        {
                            "keyword": keyword,
                            "audio_duration_ms": int(len(speech_buffer) * chunk_duration_s * 1000),
                            "source_path": "server",
                        },
                    )
                    speech_buffer = []
                    last_speech_time = now

                if is_speech:
                    last_speech_time = now
                else:
                    # Silence in LISTENING — timeout back to IDLE
                    silence_s = now - last_speech_time
                    if silence_s > config.listening_timeout_s * 0.5:
                        sm.transition(GatewayState.IDLE, reason="listening_silence_timeout")
                        speech_buffer = []
                        if kws:
                            kws.reset()

                # LISTENING overall timeout
                if (
                    sm.state == GatewayState.LISTENING
                    and sm.time_in_state() > config.listening_timeout_s
                ):
                    sm.transition(GatewayState.IDLE, reason="listening_timeout")
                    speech_buffer = []
                    if kws:
                        kws.reset()

            # ── PROCESSING: recording post-wakeword speech (Tier 3) ──
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
                        sm.transition(GatewayState.RESPONDING, reason="speech_complete")
                        full_audio = np.concatenate(speech_buffer)
                        audio_ms = int(len(full_audio) / config.server.sample_rate * 1000)

                        await _publish(
                            event_bus,
                            "voice.speech.captured",
                            {
                                "audio_duration_ms": audio_ms,
                                "source_path": "server",
                            },
                        )

                        logger.info("speech_captured: %d ms, sending to STT", audio_ms)

                        try:
                            result = await stt.transcribe(
                                full_audio,
                                sample_rate=config.server.sample_rate,
                            )
                            text = result.get("text", "").strip()
                            if text:
                                logger.info("transcript: %r", text[:80])
                                await _publish(
                                    event_bus,
                                    "voice.transcript.completed",
                                    {
                                        "text": text,
                                        "language": config.language,
                                        "engine": result.get("engine", config.server.stt_engine),
                                        "latency_ms": result.get("latency_ms", 0),
                                        "audio_duration_ms": audio_ms,
                                        "source_path": "server",
                                    },
                                )
                        except Exception as e:
                            logger.error("stt_failed: %s", e)
                            await _publish(
                                event_bus,
                                "voice.error.occurred",
                                {
                                    "error": "stt_failed",
                                    "detail": str(e),
                                    "state": "PROCESSING",
                                    "source_path": "server",
                                },
                            )

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
    app.state.metrics = {}

    # Wire reactive store
    from store import voice_store

    app.state.store = voice_store

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

# Serve WASM/static files for client-side KWS
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    from starlette.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    if _TEMPLATE_PATH.exists():
        return HTMLResponse(_TEMPLATE_PATH.read_text())
    return HTMLResponse(f"<h1>Voice Gateway</h1><p>Running on port {config.port}</p>")


def cli():
    import uvicorn

    uvicorn.run("main:app", host=config.host, port=config.port, reload=False, log_level="info")


if __name__ == "__main__":
    cli()
