"""TTS Station — Text-to-Speech service with pluggable engines.

Models are loaded on-demand and auto-unloaded after idle timeout (5min).
Supports both batch (/synthesize) and streaming SSE (/synthesize/stream).

Usage:
    cd stations/tts && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager

import uvicorn
from engines import get_engine
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

_unloader_task: asyncio.Task | None = None


async def _model_unloader_loop():
    """Background loop: check every 60s and unload idle models."""
    from engines import qwen3_tts

    try:
        from engines import kokoro
    except ImportError:
        kokoro = None

    while True:
        await asyncio.sleep(60)
        if kokoro and kokoro.is_idle():
            kokoro.unload_model()
        if qwen3_tts.is_idle():
            qwen3_tts.unload_model()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _unloader_task
    _unloader_task = asyncio.create_task(_model_unloader_loop())
    yield
    if _unloader_task:
        _unloader_task.cancel()


app = FastAPI(title="TTS Station", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "tts", "port": 10201, "streaming": True}


@app.post("/synthesize")
def synthesize(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("default", description="Voice ID"),
    speed: float = Query(1.0, description="Speech speed multiplier"),
    engine: str = Query("apple", description="Engine name"),
    format: str = Query("wav", description="Output format: wav, mp3, m4a"),
):
    """Synthesize speech from text (batch mode — returns complete file)."""
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    try:
        eng = get_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = eng.synthesize(text=text, voice=voice, speed=speed)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return JSONResponse(content=result)


@app.post("/synthesize/stream")
async def synthesize_stream(
    request: Request,
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("default", description="Voice ID"),
    speed: float = Query(1.0, description="Speech speed multiplier"),
    engine: str = Query("qwen3-tts", description="Engine name (must support streaming)"),
):
    """Stream TTS audio chunks via SSE.

    Each SSE event contains:
    - event: "audio" — base64-encoded PCM audio chunk
    - event: "meta"  — {"sample_rate": int, "chunk_idx": int}
    - event: "done"  — synthesis complete, {"total_chunks": int, "duration": float}

    Engines supporting streaming: qwen3-tts, kokoro (generator-based).
    Apple/ElevenLabs fall back to single-chunk delivery.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    _STREAMING_ENGINES = {"qwen3-tts", "kokoro"}

    try:
        eng = get_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _stream_generator():
        import numpy as np

        if engine in _STREAMING_ENGINES:
            # True streaming: yield chunks as generator produces them
            from engines import kokoro as kokoro_mod
            from engines import qwen3_tts as qwen3_mod

            if engine == "qwen3-tts":
                qwen3_mod._mark_used()
                qwen3_mod._load()
                model = qwen3_mod._model
            else:
                kokoro_mod._mark_used()
                kokoro_mod._load()
                model = kokoro_mod._model

            gen = model.generate(text, speed=speed)
            chunk_idx = 0
            total_samples = 0
            sample_rate = 24000

            for result in gen:
                if await request.is_disconnected():
                    break

                audio = np.array(result.audio, dtype=np.float32)
                sample_rate = result.sample_rate or 24000
                total_samples += len(audio)

                # First chunk: send meta
                if chunk_idx == 0:
                    yield f"event: meta\ndata: {json.dumps({'sample_rate': sample_rate, 'engine': engine})}\n\n"

                # Send audio chunk as base64 PCM float32
                audio_b64 = base64.b64encode(audio.tobytes()).decode()
                yield f"event: audio\ndata: {json.dumps({'chunk_idx': chunk_idx, 'samples': len(audio), 'audio_b64': audio_b64})}\n\n"
                chunk_idx += 1

            duration = total_samples / sample_rate if sample_rate else 0
            yield f"event: done\ndata: {json.dumps({'total_chunks': chunk_idx, 'duration': round(duration, 3)})}\n\n"

        else:
            # Fallback: batch synthesize, deliver as single SSE chunk
            result = await asyncio.to_thread(
                eng.synthesize,
                text=text,
                voice=voice,
                speed=speed,
            )
            if "error" in result:
                yield f"event: error\ndata: {json.dumps({'error': result['error']})}\n\n"
                return

            # Read the file and send as single chunk
            audio_path = result.get("audio_path", "")
            if audio_path and os.path.exists(audio_path):
                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()
                audio_b64 = base64.b64encode(audio_bytes).decode()
                sr = result.get("sample_rate", 22050)

                yield f"event: meta\ndata: {json.dumps({'sample_rate': sr, 'engine': engine, 'format': 'wav'})}\n\n"
                yield f"event: audio\ndata: {json.dumps({'chunk_idx': 0, 'samples': 0, 'audio_b64': audio_b64})}\n\n"
                yield f"event: done\ndata: {json.dumps({'total_chunks': 1, 'duration': result.get('duration', 0)})}\n\n"

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/voices")
async def list_voices(engine: str = Query("apple", description="Engine name")):
    """List available voices for an engine."""
    try:
        eng = get_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"engine": engine, "voices": eng.list_voices()}


@app.get("/engines")
async def list_engines():
    """List available TTS engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", "10201"))
    uvicorn.run(app, host="127.0.0.1", port=port)
