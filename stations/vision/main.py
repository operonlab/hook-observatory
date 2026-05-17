"""Vision Station — Visual analysis service with pluggable engines.

Models are loaded on-demand and auto-unloaded after idle timeout (5min).

Usage:
    cd stations/vision && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import asyncio
import os
import os.path
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from engines import get_engine
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sdk_client.station_bootstrap import setup_logging

setup_logging("vision", log_dir=Path("/opt/homebrew/var/log/workshop") / "vision", json=True)

_unloader_task: asyncio.Task | None = None


async def _model_unloader_loop():
    """Background loop: check every 60s and unload idle models."""
    from engines import minicpm, smolvlm, yolo

    while True:
        await asyncio.sleep(60)
        if yolo.is_idle():
            yolo.unload_model()
        if smolvlm.is_idle():
            smolvlm.unload_model()
        if minicpm.is_idle():
            minicpm.unload_model()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _unloader_task
    _unloader_task = asyncio.create_task(_model_unloader_loop())
    yield
    if _unloader_task:
        _unloader_task.cancel()


app = FastAPI(title="Vision Station", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "vision", "port": 10203}


@app.post("/analyze")
def analyze(
    path: str = Query(..., description="Absolute path to image file"),
    task: str = Query(
        "describe", description="Task: describe, detect, classify, qa, barcode, face"
    ),
    engine: str = Query("apple", description="Engine name"),
    prompt: str = Query(None, description="Free-form question (for task=qa)"),
):
    """Analyze image with specified engine and task."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    valid_tasks = {"describe", "detect", "classify", "qa", "barcode", "face"}
    if task not in valid_tasks:
        raise HTTPException(status_code=400, detail=f"Invalid task: {task}. Valid: {valid_tasks}")

    try:
        eng = get_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = eng.analyze(file_path=resolved, task=task, prompt=prompt)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    result["file"] = resolved
    return JSONResponse(content=result)


@app.get("/engines")
async def list_engines():
    """List available vision engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("VISION_PORT", "10203"))
    uvicorn.run(app, host="127.0.0.1", port=port)
