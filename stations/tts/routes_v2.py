"""/v2/* endpoints — unified OutputMode + auto-routing + capability listing.

整合 INTEGRATION-PLAN.md §2「五層架構」的 Service 層。
v1 endpoints (/synthesize, /synthesize/stream, /voices, /engines) 在 main.py 保留不動。

2026-05-19 改造：synth path 從 in-process subprocess_bridge 改用 WorkerPool
持久化常駐 worker daemon. 既有 V2_ENGINES capability metadata 仍保留 (給 /v2/engines).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import tempfile
import time
from typing import Any

import numpy as np
from engines.base_v2 import OutputMode
from engines.registry_v2 import V2_ENGINES, get_v2_engine, list_v2_engines
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from routing import explain_route, pick_engine
from schemas import EngineInfoModel, SynthesizeReqModel, SynthesizeResultModel
from worker_pool import decode_synth_response

# Per-engine "safe" RTF for streaming pre-roll calculation. Pulled from
# 2026-05-20 矩陣 worst-case + 50% safety margin. Used to advise the client
# how much initial buffer to hold before starting playback so subsequent
# segments arrive ahead of playback. Real-world RTF can spike; client should
# treat this as a minimum.
_SAFE_RTF: dict[str, float] = {
    "vibevoice": 1.2,
    "cosyvoice_v3_native": 1.5,
    "cosyvoice_v3_vllm": 1.0,
    "qwen3tts_gpu": 1.8,
    "indextts2_base": 3.5,
    "indextts2_jmica": 3.5,
}
_DEFAULT_SAFE_RTF = 2.0

# Engines beyond this RTF can't realistically stream — first-chunk pre-roll
# would need to cover the entire audio duration, defeating the point.
# /v2/synthesize/stream returns 400 for these; clients should use /v2/synthesize/long.
_STREAM_MAX_RTF = 2.5

logger = logging.getLogger(__name__)

router_v2 = APIRouter(prefix="/v2", tags=["v2"])


def _encode_audio(
    audio: np.ndarray, sr: int, output_mode: OutputMode, output_path: str | None, engine_name: str
) -> dict[str, Any]:
    """Wrap audio in the requested OutputMode and return JSONable dict."""
    duration_s = len(audio) / sr if sr else 0
    base: dict[str, Any] = {
        "duration_s": round(duration_s, 3),
        "sample_rate": int(sr),
        "engine": engine_name,
        "output_mode": output_mode.value,
    }
    if output_mode == OutputMode.FILE:
        if not output_path:
            raise HTTPException(400, "FILE mode requires output_path")
        import soundfile as sf

        sf.write(output_path, audio, sr)
        base["audio_path"] = output_path
    elif output_mode == OutputMode.BUFFER:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        base["audio_bytes_b64"] = base64.b64encode(buf.getvalue()).decode()
    elif output_mode == OutputMode.BASE64:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        base["audio_base64"] = base64.b64encode(buf.getvalue()).decode()
    else:
        raise HTTPException(
            400,
            f"OutputMode {output_mode.value} not supported via worker_pool (use file/buffer/base64)",
        )
    return base


def _resolve_engine_name(req: SynthesizeReqModel) -> str:
    if req.engine != "auto":
        if req.engine not in V2_ENGINES:
            raise HTTPException(400, f"unknown engine: {req.engine}")
        return req.engine
    try:
        return pick_engine(req.lang, available=V2_ENGINES.keys())
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router_v2.post("/synthesize", response_model=SynthesizeResultModel)
async def synthesize_v2(req: SynthesizeReqModel, request: Request) -> SynthesizeResultModel:
    """合成語音 — auto routing + WorkerPool 持久化 dispatch."""
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        raise HTTPException(503, "WorkerPool not initialized")

    engine_name = _resolve_engine_name(req)
    output_mode = OutputMode(req.output)
    output_path = req.output_path
    if output_mode == OutputMode.FILE and not output_path:
        output_path = tempfile.mktemp(suffix=".wav", prefix=f"tts_{engine_name}_")

    ref_text = req.engine_specific.get("ref_text") if req.engine_specific else None
    try:
        resp = await pool.synth(
            engine_name=engine_name,
            text=req.text,
            lang=req.lang,
            voice_id=req.voice_id,
            speed=req.speed,
            ref_text=ref_text,
        )
        audio, sr = decode_synth_response(resp)
    except RuntimeError as e:
        logger.exception("v2 synth failed (%s)", engine_name)
        raise HTTPException(500, str(e)) from e

    payload = _encode_audio(audio, sr, output_mode, output_path, engine_name)
    payload["rtf"] = resp.get("rtf", 0.0)
    return SynthesizeResultModel(**payload)


@router_v2.post("/synthesize/long")
async def synthesize_v2_long(payload: dict, request: Request) -> dict:
    """合成長文 — 自動切段 + 同段 engine batch + numpy concat 回傳完整 wav.

    body:
      {"engine": "auto"|"<name>",
       "text": "...long...",
       "lang": "zh"|"en"|"ja"|"ko",
       "voice_id": "master",
       "speed": 1.0,
       "max_chars": <int optional>,        # override per-lang default
       "output": "file"|"buffer"|"base64",
       "output_path": "..." (file mode)}

    Returns: same shape as /v2/synthesize plus `segments`, `seg_durations_s`.

    PR-A: plain np.concat between segments (no silence padding / crossfade).
    """
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        raise HTTPException(503, "WorkerPool not initialized")

    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    lang = payload.get("lang", "zh")
    voice_id = payload.get("voice_id", "master")
    speed = payload.get("speed", 1.0)
    max_chars = payload.get("max_chars")
    output_mode = OutputMode(payload.get("output", "buffer"))
    output_path = payload.get("output_path")
    if output_mode == OutputMode.FILE and not output_path:
        output_path = tempfile.mktemp(suffix=".wav", prefix="tts_long_")

    # Engine resolve (auto or explicit)
    engine_param = payload.get("engine", "auto")
    if engine_param == "auto":
        try:
            engine_name = pick_engine(lang, available=V2_ENGINES.keys())
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
    else:
        if engine_param not in V2_ENGINES:
            raise HTTPException(400, f"unknown engine: {engine_param}")
        engine_name = engine_param

    from text_segmenter import split_for_tts

    chunks = split_for_tts(text, lang=lang, max_chars=max_chars)
    if not chunks:
        raise HTTPException(400, "text resolved to zero chunks")

    items = [{"text": c, "lang": lang, "voice_id": voice_id, "speed": speed} for c in chunks]
    try:
        resps = await pool.synth_batch(engine_name, items)
    except RuntimeError as e:
        logger.exception("v2 long synth failed (%s)", engine_name)
        raise HTTPException(500, str(e)) from e

    audios: list[np.ndarray] = []
    seg_durs: list[float] = []
    sr = 24000
    for i, resp in enumerate(resps):
        if not resp.get("ok"):
            raise HTTPException(500, f"segment {i} failed: {resp.get('error', '?')}")
        a, s = decode_synth_response(resp)
        audios.append(a)
        sr = s
        seg_durs.append(round(len(a) / s, 3))

    full = np.concatenate(audios) if len(audios) > 1 else audios[0]
    payload_out = _encode_audio(full, sr, output_mode, output_path, engine_name)
    payload_out["segments"] = len(chunks)
    payload_out["seg_durations_s"] = seg_durs
    payload_out["seg_chunks"] = chunks  # echo back for debugging
    return payload_out


@router_v2.post("/synthesize/stream")
async def synthesize_v2_stream(payload: dict, request: Request):
    """SSE 偽串流 — 切段 → 逐段合成 → 邊產邊吐 audio events.

    Engines 本身不支援 streaming generate；station 在外面切段並以 SSE 緩送
    PCM chunk，client 在收到第一段後等 pre_roll_sec 再開播即可平滑接續播放。

    body 同 /v2/synthesize/long; SSE events:
      event: meta   data: {engine, sample_rate, total_segments, pre_roll_sec, expected_total_dur_s, seg_chunks}
      event: audio  data: {chunk_idx, samples, duration_s, audio_b64 (raw float32 PCM)}
      event: done   data: {total_chunks, total_duration_s, wall_s}
      event: error  data: {error, chunk_idx?}
    """
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        raise HTTPException(503, "WorkerPool not initialized")

    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    lang = payload.get("lang", "zh")
    voice_id = payload.get("voice_id", "master")
    speed = payload.get("speed", 1.0)
    max_chars = payload.get("max_chars")
    ref_text = payload.get("ref_text")

    engine_param = payload.get("engine", "auto")
    if engine_param == "auto":
        try:
            engine_name = pick_engine(lang, available=V2_ENGINES.keys())
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
    else:
        if engine_param not in V2_ENGINES:
            raise HTTPException(400, f"unknown engine: {engine_param}")
        engine_name = engine_param

    # Engines with safe_rtf > _STREAM_MAX_RTF are too slow for SSE — the
    # client would have to pre-roll the entire audio before press-play,
    # defeating the point. Refuse and tell the client to use /v2/synthesize/long.
    safe_rtf = _SAFE_RTF.get(engine_name, _DEFAULT_SAFE_RTF)
    if safe_rtf > _STREAM_MAX_RTF:
        raise HTTPException(
            400,
            f"engine '{engine_name}' has safe_rtf={safe_rtf} > {_STREAM_MAX_RTF}; "
            f"stream mode would require pre-rolling the full audio. "
            f"Use /v2/synthesize/long instead.",
        )

    from text_segmenter import split_for_tts

    chunks = split_for_tts(text, lang=lang, max_chars=max_chars)
    if not chunks:
        raise HTTPException(400, "text resolved to zero chunks")

    # Pre-roll heuristic (2026-05-20 修補): use max chunk dur (not avg) × safe_rtf
    # × 1.5 buffer factor. Earlier "avg × (rtf - 1)" was too optimistic — the
    # longest middle segment dominates stall risk (it must finish generating
    # before its predecessor finishes playing).
    chars_per_sec = {"zh": 4.0, "ja": 4.0, "ko": 4.0, "en": 2.5}.get(lang, 4.0)
    max_seg_chars = max(len(c) for c in chunks)
    max_seg_dur = max_seg_chars / chars_per_sec
    pre_roll_sec = round(max(1.0, max_seg_dur * safe_rtf * 1.5 - max_seg_dur), 2)
    expected_total_dur = round(sum(len(c) for c in chunks) / chars_per_sec, 2)

    def _sse(event: str, data: dict) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

    async def _gen():
        wall0 = time.monotonic()
        yield _sse(
            "meta",
            {
                "engine": engine_name,
                "lang": lang,
                "voice_id": voice_id,
                "sample_rate": 24000,
                "total_segments": len(chunks),
                "pre_roll_sec": pre_roll_sec,
                "safe_rtf": safe_rtf,
                "expected_total_dur_s": expected_total_dur,
                "seg_chunks": chunks,
            },
        )
        total_samples = 0
        sr = 24000
        for idx, chunk in enumerate(chunks):
            if await request.is_disconnected():
                logger.info("client disconnected on chunk %d/%d", idx, len(chunks))
                return
            try:
                resp = await pool.synth(
                    engine_name=engine_name,
                    text=chunk,
                    lang=lang,
                    voice_id=voice_id,
                    speed=speed,
                    ref_text=ref_text,
                )
                audio, sr = decode_synth_response(resp)
            except Exception as e:
                logger.exception("stream chunk %d failed", idx)
                yield _sse("error", {"error": str(e), "chunk_idx": idx})
                return
            total_samples += len(audio)
            yield _sse(
                "audio",
                {
                    "chunk_idx": idx,
                    "samples": len(audio),
                    "duration_s": round(len(audio) / sr, 3),
                    "audio_b64": base64.b64encode(audio.astype(np.float32).tobytes()).decode(),
                },
            )
        yield _sse(
            "done",
            {
                "total_chunks": len(chunks),
                "total_duration_s": round(total_samples / sr, 3),
                "wall_s": round(time.monotonic() - wall0, 2),
                "sample_rate": int(sr),
            },
        )

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router_v2.post("/synthesize/batch")
async def synthesize_v2_batch(payload: dict, request: Request) -> dict:
    """Batch synth — items list 共用 keep-alive worker，避免每句 swap engine.

    body:
      {"engine": "auto"|"<name>", "lang": "<auto-per-item or default>",
       "items": [{"text": "...", "lang": "zh", "voice_id": "master", "ref_text": "..."}, ...],
       "output": "file"|"buffer"|"base64",
       "output_dir": "..." (file mode 必填)}
    """
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        raise HTTPException(503, "WorkerPool not initialized")
    items = payload.get("items") or []
    if not items:
        raise HTTPException(400, "items list required")

    engine_param = payload.get("engine", "auto")
    output = payload.get("output", "file")
    output_dir = payload.get("output_dir")
    output_mode = OutputMode(output)
    if output_mode == OutputMode.FILE and not output_dir:
        raise HTTPException(400, "FILE batch requires output_dir")

    # Group items by resolved engine; default 自動 routing per item.lang
    resolved: list[tuple[str, dict]] = []
    for it in items:
        if engine_param != "auto":
            eng = engine_param
        else:
            eng = pick_engine(it.get("lang", "zh"), available=V2_ENGINES.keys())
        resolved.append((eng, it))

    # Sort by engine to maximize keep-alive runs
    groups: dict[str, list[tuple[int, dict]]] = {}
    for idx, (eng, it) in enumerate(resolved):
        groups.setdefault(eng, []).append((idx, it))

    results: list[dict] = [None] * len(items)
    for eng, group_items in groups.items():
        only = [it for _idx, it in group_items]
        try:
            resps = await pool.synth_batch(eng, only)
        except RuntimeError as e:
            for idx, _ in group_items:
                results[idx] = {"ok": False, "engine": eng, "error": str(e)}
            continue
        for (idx, it), resp in zip(group_items, resps):
            if not resp.get("ok"):
                results[idx] = {"ok": False, "engine": eng, "error": resp.get("error")}
                continue
            try:
                audio, sr = decode_synth_response(resp)
                if output_mode == OutputMode.FILE:
                    fname = it.get("filename") or f"batch_{idx}_{eng}.wav"
                    out_path = os.path.join(output_dir, fname)
                    payload_one = _encode_audio(audio, sr, OutputMode.FILE, out_path, eng)
                else:
                    payload_one = _encode_audio(audio, sr, output_mode, None, eng)
                payload_one["rtf"] = resp.get("rtf", 0.0)
                results[idx] = {"ok": True, **payload_one}
            except Exception as e:
                results[idx] = {"ok": False, "engine": eng, "error": str(e)}

    return {"count": len(results), "results": results}


@router_v2.get("/engines")
async def list_engines_v2(request: Request) -> dict:
    """List engine capabilities + live worker_pool status."""
    pool = getattr(request.app.state, "worker_pool", None)
    pool_status = await pool.status() if pool else {"error": "pool not initialized"}
    return {
        "version": 2,
        "count": len(list_v2_engines()),
        "engines": list_v2_engines(),
        "pool": pool_status,
    }


@router_v2.get("/engines/{name}", response_model=EngineInfoModel)
def engine_detail(name: str) -> EngineInfoModel:
    try:
        eng = get_v2_engine(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    cap = eng.capability()
    return EngineInfoModel(
        name=cap.name,
        languages=cap.languages,
        multi_speaker=cap.multi_speaker,
        rtf_typical=cap.rtf_typical,
        vram_mb=cap.vram_mb,
        needs_wsl=cap.needs_wsl,
        needs_gpu=cap.needs_gpu,
        supported_outputs=[o.value for o in cap.supported_outputs],
        sample_rate=cap.sample_rate,
        loaded=False,
        idle_sec=None,
        notes=cap.notes,
    )


@router_v2.get("/voices")
def list_voices_v2() -> dict:
    voices_dir = os.environ.get(
        "STATIONS_TTS_VOICES",
        str(os.path.join(os.path.dirname(__file__), "voices")),
    )
    out = []
    if os.path.isdir(voices_dir):
        seen = set()
        for fname in os.listdir(voices_dir):
            if fname.endswith(".wav"):
                seen.add(fname[:-4])
        for voice_id in sorted(seen):
            meta_file = os.path.join(voices_dir, f"{voice_id}.meta.yaml")
            transcript_file = os.path.join(voices_dir, f"{voice_id}.transcript")
            out.append(
                {
                    "voice_id": voice_id,
                    "has_transcript": os.path.exists(transcript_file),
                    "has_meta": os.path.exists(meta_file),
                }
            )
    return {"voices_dir": voices_dir, "voices": out}


@router_v2.get("/route")
def route_debug(lang: str, multi_speaker: bool = False, prefer_fast: bool = False) -> dict:
    return explain_route(lang, multi_speaker=multi_speaker, prefer_fast=prefer_fast)


@router_v2.get("/pool")
async def pool_status(request: Request) -> dict:
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        return {"error": "pool not initialized"}
    return await pool.status()


@router_v2.post("/pool/unload")
async def pool_unload(request: Request) -> dict:
    """Force unload current engine (for testing / GPU recovery)."""
    pool = getattr(request.app.state, "worker_pool", None)
    if pool is None:
        raise HTTPException(503, "WorkerPool not initialized")
    async with pool._lock:
        if pool.active_engine and pool.active_worker_id:
            await pool.workers[pool.active_worker_id].send({"op": "unload"}, timeout=30.0)
            pool.active_engine = None
            pool.active_worker_id = None
    return await pool.status()


@router_v2.get("/healthz")
async def healthz(request: Request) -> dict:
    pool = getattr(request.app.state, "worker_pool", None)
    return {"version": 2, "pool": (await pool.status()) if pool else {"error": "not initialized"}}
