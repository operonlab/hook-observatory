"""STT Station — Speech-to-Text service with pluggable engines.

Models are loaded on-demand and auto-unloaded after idle timeout (5min).
Supports batch (/transcribe) and pseudo-streaming WebSocket (/transcribe/stream).

Usage:
    cd stations/stt && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from engines import get_engine
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse

_unloader_task: asyncio.Task | None = None


async def _model_unloader_loop():
    """Background loop: check every 60s and unload idle models."""
    from engines import mlx_whisper, qwen3_asr

    while True:
        await asyncio.sleep(60)
        if mlx_whisper.is_idle():
            mlx_whisper.unload_model()
        if qwen3_asr.is_idle():
            qwen3_asr.unload_model()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _unloader_task
    _unloader_task = asyncio.create_task(_model_unloader_loop())
    yield
    if _unloader_task:
        _unloader_task.cancel()


app = FastAPI(title="STT Station", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stt", "port": 10200, "streaming": True}


# ======================== Subtitle Helpers ========================


def _seg_end(seg: dict) -> float:
    """Get segment end time — handles both 'end' and 'start+duration' formats."""
    if "end" in seg:
        return seg["end"]
    return seg.get("start", 0) + seg.get("duration", 0)


def _to_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_time_srt(seg.get("start", 0))
        end = _format_time_srt(_seg_end(seg))
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = _format_time_vtt(seg.get("start", 0))
        end = _format_time_vtt(_seg_end(seg))
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _format_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_time_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ======================== Batch Endpoint ========================


@app.post("/transcribe")
async def transcribe(
    path: str = Query(..., description="Absolute path to audio file"),
    language: str = Query("zh-TW", description="Language code"),
    engine: str = Query("apple", description="Engine name"),
    format: str = Query("json", description="Output format: json, srt, vtt, text"),
):
    """Transcribe audio file to text (batch mode)."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if format not in ("json", "srt", "vtt", "text"):
        raise HTTPException(status_code=400, detail=f"Invalid format: {format}")

    try:
        eng = get_engine(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = eng.transcribe(str(file_path), language=language)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    if format == "text":
        return PlainTextResponse(content=result.get("text", ""))
    elif format == "srt":
        return PlainTextResponse(
            content=_to_srt(result.get("segments", [])), media_type="text/plain"
        )
    elif format == "vtt":
        return PlainTextResponse(content=_to_vtt(result.get("segments", [])), media_type="text/vtt")

    return JSONResponse(content=result)


# ======================== Streaming Endpoint ========================


@app.websocket("/transcribe/stream")
async def transcribe_stream(ws: WebSocket):
    """Pseudo-streaming STT via WebSocket.

    Protocol:
    1. Client sends JSON config: {"engine": "mlx-whisper", "language": "zh-TW",
       "sample_rate": 16000, "buffer_ms": 1000}
    2. Client sends raw PCM bytes (16-bit signed, mono)
    3. Server sends partial results: {"type": "partial", "text": "...", "latency_ms": N}
    4. Client sends JSON {"type": "end"} to finalize
    5. Server sends final: {"type": "final", "text": "...", "segments": [...]}

    Target latency: ~1.2s (1.0s buffer + 0.2s inference on M4).
    Strategy: accumulate all audio, re-transcribe full buffer each interval,
    diff against previous result for incremental text.
    """
    await ws.accept()

    try:
        # Step 1: receive config
        config_raw = await ws.receive_text()
        config = json.loads(config_raw)
        engine_name = config.get("engine", "mlx-whisper")
        language = config.get("language", "zh-TW")
        sample_rate = config.get("sample_rate", 16000)
        buffer_ms = config.get("buffer_ms", 1000)  # target ~1.0s

        try:
            eng = get_engine(engine_name)
        except ValueError as e:
            await ws.send_json({"type": "error", "error": str(e)})
            await ws.close()
            return

        await ws.send_json({"type": "ready", "engine": engine_name, "buffer_ms": buffer_ms})

        # Step 2: receive audio chunks, transcribe at intervals
        audio_buffer = bytearray()
        prev_text = ""
        samples_per_interval = int(sample_rate * buffer_ms / 1000) * 2  # 16-bit = 2 bytes/sample
        last_transcribe_time = 0.0
        interval_s = buffer_ms / 1000.0

        while True:
            msg = await ws.receive()

            if msg.get("type") == "websocket.receive":
                if msg.get("bytes"):
                    audio_buffer.extend(msg["bytes"])

                    # Check if enough audio accumulated since last transcription
                    now = time.monotonic()
                    if (now - last_transcribe_time) >= interval_s and len(
                        audio_buffer
                    ) >= samples_per_interval:
                        last_transcribe_time = now

                        # Write accumulated audio to temp file
                        result = await _transcribe_buffer(
                            bytes(audio_buffer),
                            sample_rate,
                            eng,
                            language,
                        )
                        new_text = result.get("text", "").strip()

                        if new_text and new_text != prev_text:
                            # Calculate incremental text
                            incremental = _diff_text(prev_text, new_text)
                            latency_ms = int((time.monotonic() - now) * 1000)
                            prev_text = new_text

                            await ws.send_json(
                                {
                                    "type": "partial",
                                    "text": new_text,
                                    "delta": incremental,
                                    "latency_ms": latency_ms,
                                    "audio_duration_ms": int(
                                        len(audio_buffer) / 2 / sample_rate * 1000
                                    ),
                                }
                            )

                elif msg.get("text"):
                    data = json.loads(msg["text"])
                    if data.get("type") == "end":
                        break
            else:
                break

        # Step 3: final transcription on complete audio
        if audio_buffer:
            result = await _transcribe_buffer(
                bytes(audio_buffer),
                sample_rate,
                eng,
                language,
            )
            await ws.send_json(
                {
                    "type": "final",
                    "text": result.get("text", "").strip(),
                    "segments": result.get("segments", []),
                    "engine": engine_name,
                    "audio_duration_ms": int(len(audio_buffer) / 2 / sample_rate * 1000),
                }
            )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


async def _transcribe_buffer(audio_bytes: bytes, sample_rate: int, eng, language: str) -> dict:
    """Write audio buffer to temp WAV file and transcribe."""
    import wave

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)

    try:
        result = await asyncio.to_thread(eng.transcribe, tmp_path, language)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result


def _diff_text(prev: str, current: str) -> str:
    """Extract new text that wasn't in previous transcription."""
    if not prev:
        return current
    # Find the longest common prefix
    i = 0
    min_len = min(len(prev), len(current))
    while i < min_len and prev[i] == current[i]:
        i += 1
    return current[i:].strip()


@app.get("/engines")
async def list_engines():
    """List available STT engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("STT_PORT", "10200"))
    uvicorn.run(app, host="127.0.0.1", port=port)
