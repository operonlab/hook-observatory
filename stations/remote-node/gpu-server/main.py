"""GPU Server — FastAPI application serving Florence-2 inference over HTTP.

Designed to run on a Windows PC with an RTX 3090 (also works on Linux).
Start with:  uvicorn main:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import torch
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from engines import get_all_engines, get_engine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gpu-server")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CFG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    if _CFG_PATH.exists():
        with open(_CFG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


CONFIG = _load_config()
IDLE_TIMEOUT: int = CONFIG.get("idle_timeout", 300)
UNLOAD_INTERVAL: int = CONFIG.get("unload_interval", 60)
MAX_IMAGE_SIZE: int = CONFIG.get("max_image_size", 2048)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vram_info() -> tuple[float, float]:
    """Return (used_gb, total_gb).  Falls back to (0, 0) if CUDA unavailable."""
    if not torch.cuda.is_available():
        return 0.0, 0.0
    free, total = torch.cuda.mem_get_info()
    total_gb = round(total / (1024**3), 2)
    used_gb = round((total - free) / (1024**3), 2)
    return used_gb, total_gb


def _gpu_name() -> str:
    if torch.cuda.is_available():
        return torch.cuda.get_device_name(0)
    return "no-gpu"


def _decode_image(b64: str) -> Image.Image:
    """Decode a base64-encoded image to PIL, resize if larger than MAX_IMAGE_SIZE."""
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_SIZE:
        scale = MAX_IMAGE_SIZE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        log.info("Resized image from %dx%d to %dx%d", w, h, img.width, img.height)
    return img


def _encode_image_b64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def _polygons_to_mask(
    polygons: list[list[float]], width: int, height: int
) -> Image.Image:
    """Render polygons onto a transparent RGBA mask image."""
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(mask)
    for poly in polygons:
        if len(poly) < 4:
            continue
        # Convert flat [x1,y1,x2,y2,...] to list of (x,y) tuples
        points = [(poly[i], poly[i + 1]) for i in range(0, len(poly) - 1, 2)]
        if len(points) >= 3:
            draw.polygon(points, fill=(0, 255, 0, 128), outline=(0, 255, 0, 255))
    return mask


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SegmentRequest(BaseModel):
    image_b64: str
    prompt: str


class DetectRequest(BaseModel):
    image_b64: str
    prompt: str


class CaptionRequest(BaseModel):
    image_b64: str
    detail: str = Field(default="brief", pattern="^(brief|detailed)$")


class BatchSegmentRequest(BaseModel):
    image_b64: str
    prompts: list[str]


class ModelActionRequest(BaseModel):
    model: str


# ---------------------------------------------------------------------------
# Lifespan — background model unloader
# ---------------------------------------------------------------------------


async def _model_unloader() -> None:
    """Periodically check for idle engines and unload them."""
    while True:
        await asyncio.sleep(UNLOAD_INTERVAL)
        now = time.time()
        for name, engine in get_all_engines().items():
            if engine.is_loaded() and engine.last_used() > 0:
                idle = now - engine.last_used()
                if idle > IDLE_TIMEOUT:
                    log.info(
                        "Engine '%s' idle for %.0fs (limit %ds) — unloading.",
                        name,
                        idle,
                        IDLE_TIMEOUT,
                    )
                    await asyncio.to_thread(engine.unload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("GPU Server starting — GPU: %s", _gpu_name())
    used, total = _vram_info()
    log.info("VRAM: %.2f / %.2f GB", used, total)

    # Auto-load models flagged in config
    models_cfg = CONFIG.get("models", {})
    for model_name, mcfg in models_cfg.items():
        if mcfg.get("auto_load", False):
            engine = get_engine(model_name)
            if engine:
                log.info("Auto-loading engine '%s' ...", model_name)
                await asyncio.to_thread(engine.load)

    task = asyncio.create_task(_model_unloader())
    yield
    task.cancel()
    log.info("GPU Server shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="GPU Server",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    used, total = _vram_info()
    loaded = [n for n, e in get_all_engines().items() if e.is_loaded()]
    return {
        "status": "ok",
        "gpu": _gpu_name(),
        "vram_used_gb": used,
        "vram_total_gb": total,
        "models_loaded": loaded,
    }


@app.get("/models")
async def list_models():
    out: list[dict[str, Any]] = []
    for name, engine in get_all_engines().items():
        out.append(
            {
                "name": name,
                "loaded": engine.is_loaded(),
                "vram_mb": engine.vram_mb(),
                "last_used": engine.last_used(),
            }
        )
    return {"models": out}


@app.post("/models/load")
async def load_model(req: ModelActionRequest):
    engine = get_engine(req.model)
    if engine is None:
        raise HTTPException(404, f"Unknown model: {req.model}")
    if engine.is_loaded():
        return {"status": "already_loaded", "model": req.model}
    await asyncio.to_thread(engine.load)
    return {"status": "loaded", "model": req.model}


@app.post("/models/unload")
async def unload_model(req: ModelActionRequest):
    engine = get_engine(req.model)
    if engine is None:
        raise HTTPException(404, f"Unknown model: {req.model}")
    if not engine.is_loaded():
        return {"status": "already_unloaded", "model": req.model}
    await asyncio.to_thread(engine.unload)
    return {"status": "unloaded", "model": req.model}


# ---------------------------------------------------------------------------
# Florence-2 inference endpoints
# ---------------------------------------------------------------------------


def _get_florence():
    engine = get_engine("florence2")
    if engine is None:
        raise HTTPException(500, "Florence-2 engine not registered")
    return engine


@app.post("/segment")
async def segment(req: SegmentRequest):
    engine = _get_florence()

    # Auto-load: return 503 while loading is in progress
    if not engine.is_loaded():
        log.info("Florence-2 not loaded — auto-loading for /segment request ...")
        try:
            await asyncio.to_thread(engine.load)
        except Exception as exc:
            raise HTTPException(503, f"Model loading failed: {exc}") from exc

    image = _decode_image(req.image_b64)
    result = await asyncio.to_thread(engine.segment, image, req.prompt)

    # Render mask from polygons
    mask = _polygons_to_mask(result["polygons"], image.width, image.height)
    mask_b64 = _encode_image_b64(mask)

    return {
        "polygons": result["polygons"],
        "labels": result["labels"],
        "mask_b64": mask_b64,
        "image_size": [image.width, image.height],
    }


@app.post("/detect")
async def detect(req: DetectRequest):
    engine = _get_florence()

    if not engine.is_loaded():
        log.info("Florence-2 not loaded — auto-loading for /detect request ...")
        try:
            await asyncio.to_thread(engine.load)
        except Exception as exc:
            raise HTTPException(503, f"Model loading failed: {exc}") from exc

    image = _decode_image(req.image_b64)
    result = await asyncio.to_thread(engine.detect, image, req.prompt)

    return {
        "boxes": result["boxes"],
        "labels": result["labels"],
        "scores": result["scores"],
        "image_size": [image.width, image.height],
    }


@app.post("/caption")
async def caption(req: CaptionRequest):
    engine = _get_florence()

    if not engine.is_loaded():
        log.info("Florence-2 not loaded — auto-loading for /caption request ...")
        try:
            await asyncio.to_thread(engine.load)
        except Exception as exc:
            raise HTTPException(503, f"Model loading failed: {exc}") from exc

    image = _decode_image(req.image_b64)
    result = await asyncio.to_thread(engine.caption, image, req.detail)

    return {"caption": result["caption"]}


@app.post("/batch-segment")
async def batch_segment(req: BatchSegmentRequest):
    engine = _get_florence()

    if not engine.is_loaded():
        log.info("Florence-2 not loaded — auto-loading for /batch-segment request ...")
        try:
            await asyncio.to_thread(engine.load)
        except Exception as exc:
            raise HTTPException(503, f"Model loading failed: {exc}") from exc

    image = _decode_image(req.image_b64)
    result = await asyncio.to_thread(engine.batch_segment, image, req.prompts)

    # Build composite mask from all prompts
    all_polygons: list[list[float]] = []
    for prompt_result in result["results"].values():
        all_polygons.extend(prompt_result.get("polygons", []))

    composite_mask = _polygons_to_mask(all_polygons, image.width, image.height)
    composite_mask_b64 = _encode_image_b64(composite_mask)

    return {
        "results": result["results"],
        "composite_mask_b64": composite_mask_b64,
        "image_size": [image.width, image.height],
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = CONFIG.get("host", "0.0.0.0")
    port = CONFIG.get("port", 7860)
    log.info("Starting GPU Server on %s:%d", host, port)
    uvicorn.run("main:app", host=host, port=port, log_level="info")
