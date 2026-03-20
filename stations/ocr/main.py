"""OCR Station — Text extraction service with pluggable engines.

Usage:
    cd stations/ocr && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from engines import get_engine

app = FastAPI(title="OCR Station", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ocr", "port": 4109}


@app.post("/extract")
async def extract(
    path: str = Query(..., description="Absolute path to image or PDF file"),
    languages: str = Query("zh-Hant,en", description="Comma-separated language codes"),
    engine: str = Query("apple", description="Engine name"),
):
    """Extract text from image or PDF."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        eng = get_engine(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    lang_list = [l.strip() for l in languages.split(",")]
    result = eng.extract(str(file_path), languages=lang_list)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return JSONResponse(content=result)


@app.get("/engines")
async def list_engines():
    """List available OCR engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("OCR_PORT", "4109"))
    uvicorn.run(app, host="127.0.0.1", port=port)
