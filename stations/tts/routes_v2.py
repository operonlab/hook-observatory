"""/v2/* endpoints — unified OutputMode + auto-routing + capability listing.

整合 INTEGRATION-PLAN.md §2「五層架構」的 Service 層。v1 endpoints
(/synthesize, /synthesize/stream, /voices, /engines) 在 main.py 保留不動。
"""

from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException

from engines.base_v2 import OutputMode, SynthesizeRequest
from engines.registry_v2 import V2_ENGINES, get_v2_engine, list_v2_engines
from lifecycle import MANAGER
from routing import explain_route, pick_engine
from schemas import EngineInfoModel, SynthesizeReqModel, SynthesizeResultModel

logger = logging.getLogger(__name__)

router_v2 = APIRouter(prefix="/v2", tags=["v2"])


@router_v2.post("/synthesize", response_model=SynthesizeResultModel)
def synthesize_v2(req: SynthesizeReqModel) -> SynthesizeResultModel:
    """合成語音 — 統一 OutputMode + auto routing 入口."""

    engine_name = req.engine
    if engine_name == "auto":
        try:
            engine_name = pick_engine(req.lang, available=V2_ENGINES.keys())
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        engine = get_v2_engine(engine_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    output_mode = OutputMode(req.output)
    output_path = req.output_path
    if output_mode == OutputMode.FILE and not output_path:
        output_path = tempfile.mktemp(suffix=".wav", prefix=f"tts_{engine_name}_")

    eng_req = SynthesizeRequest(
        text=req.text,
        lang=req.lang,
        voice_id=req.voice_id,
        output=output_mode,
        output_path=output_path,
        target_sample_rate=req.target_sample_rate,
        speed=req.speed,
        engine_specific=req.engine_specific,
    )

    MANAGER.mark_used(engine_name)
    try:
        result = engine.synthesize(eng_req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.exception("v2 synth failed (%s)", engine_name)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return SynthesizeResultModel(**result.to_jsonable())


@router_v2.get("/engines")
def list_engines_v2() -> dict:
    """列 v2 engine + capability + 健康狀態."""
    engines = list_v2_engines()
    return {
        "version": 2,
        "count": len(engines),
        "engines": engines,
        "lifecycle": MANAGER.status(),
    }


@router_v2.get("/engines/{name}", response_model=EngineInfoModel)
def engine_detail(name: str) -> EngineInfoModel:
    try:
        eng = get_v2_engine(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    cap = eng.capability()
    status = MANAGER.status().get(name, {})
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
        loaded=eng.healthcheck().get("ok", False),
        idle_sec=status.get("idle_sec"),
        notes=cap.notes,
    )


@router_v2.get("/voices")
def list_voices_v2() -> dict:
    """掃描 voices/ 目錄列已知 voice."""
    voices_dir = os.environ.get(
        "STATIONS_TTS_VOICES",
        str(os.path.join(os.path.dirname(__file__), "voices")),
    )
    out = []
    if os.path.isdir(voices_dir):
        seen = set()
        for fname in os.listdir(voices_dir):
            if fname.endswith(".wav"):
                voice_id = fname[:-4]
                seen.add(voice_id)
        for voice_id in sorted(seen):
            meta_file = os.path.join(voices_dir, f"{voice_id}.meta.yaml")
            transcript_file = os.path.join(voices_dir, f"{voice_id}.transcript")
            out.append({
                "voice_id": voice_id,
                "has_transcript": os.path.exists(transcript_file),
                "has_meta": os.path.exists(meta_file),
            })
    return {"voices_dir": voices_dir, "voices": out}


@router_v2.get("/route")
def route_debug(lang: str, multi_speaker: bool = False, prefer_fast: bool = False) -> dict:
    return explain_route(lang, multi_speaker=multi_speaker, prefer_fast=prefer_fast)


@router_v2.post("/lifecycle/sweep")
def lifecycle_sweep() -> dict:
    unloaded = MANAGER.sweep()
    return {"unloaded": unloaded, "status_after": MANAGER.status()}


@router_v2.get("/lifecycle")
def lifecycle_status() -> dict:
    return MANAGER.status()


@router_v2.get("/healthz")
def healthz() -> dict:
    return {
        "version": 2,
        "engines": {name: eng.healthcheck() for name, eng in V2_ENGINES.items()},
        "lifecycle": MANAGER.status(),
    }
