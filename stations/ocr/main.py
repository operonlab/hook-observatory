"""OCR Station — Text extraction service with pluggable engines.

Models are loaded on-demand and auto-unloaded after idle timeout (5min)
to avoid persistent ~1.5GB memory usage from PaddleOCR.

Usage:
    cd stations/ocr && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import asyncio
import os
import os.path
from pathlib import Path

import uvicorn
from engines import get_engine
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sdk_client.station_bootstrap import setup_logging

setup_logging("ocr", log_dir=Path("/opt/homebrew/var/log/workshop") / "ocr", json=True)

_unloader_task: asyncio.Task | None = None


async def _model_unloader_loop():
    """Background loop: check every 60s and unload idle PaddleOCR models."""
    from engines.paddle import is_idle, unload_models

    while True:
        await asyncio.sleep(60)
        if is_idle():
            unload_models()


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _unloader_task
    _unloader_task = asyncio.create_task(_model_unloader_loop())
    yield
    if _unloader_task:
        _unloader_task.cancel()


app = FastAPI(title="OCR Station", version="0.3.0", lifespan=lifespan)

# Engines with built-in preprocessing — skip external preprocessing in auto mode
_SELF_PREPROCESSING_ENGINES = {"paddle", "claude", "gemini"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ocr", "port": 10202}


@app.post("/extract")
def extract(
    path: str = Query(..., description="Absolute path to image or PDF file"),
    languages: str = Query("zh-Hant,en", description="Comma-separated language codes"),
    engine: str = Query("apple", description="Engine name"),
    preprocess: str = Query("auto", description="Preprocessing: 'auto', 'on', or 'off'"),
):
    """Extract text from image or PDF."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        eng = get_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Apply preprocessing pipeline
    # auto mode: only for engines without built-in preprocessing (apple, tesseract)
    # on mode: force preprocessing regardless of engine
    actual_path = resolved
    preprocessed = False
    should_preprocess = preprocess == "on" or (
        preprocess == "auto" and engine not in _SELF_PREPROCESSING_ENGINES
    )
    if should_preprocess and not resolved.lower().endswith(".pdf"):
        from preprocessing import preprocess as pp

        force = preprocess == "on"
        pp_path = pp(actual_path, force=force)
        if pp_path != actual_path:
            preprocessed = True
            actual_path = pp_path

    lang_list = [lang.strip() for lang in languages.split(",")]
    result = eng.extract(actual_path, languages=lang_list)

    # Clean up temp file
    if preprocessed:
        try:
            os.unlink(actual_path)
        except OSError:
            pass

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    result["preprocessed"] = preprocessed
    result["file"] = resolved
    return JSONResponse(content=result)


@app.get("/engines")
async def list_engines():
    """List available OCR engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("OCR_PORT", "10202"))
    uvicorn.run(app, host="127.0.0.1", port=port)
