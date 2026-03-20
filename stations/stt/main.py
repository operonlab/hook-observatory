"""STT Station -- Speech-to-Text service with pluggable engines.

Usage:
    cd stations/stt && .venv/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from engines import get_engine

app = FastAPI(title="STT Station", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stt", "port": 4108}


@app.post("/transcribe")
async def transcribe(
    path: str = Query(..., description="Absolute path to audio file"),
    language: str = Query("zh-TW", description="Language code"),
    engine: str = Query("apple", description="Engine name"),
):
    """Transcribe audio file to text."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        eng = get_engine(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = eng.transcribe(str(file_path), language=language)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return JSONResponse(content=result)


@app.get("/engines")
async def list_engines():
    """List available STT engines."""
    from engines import ENGINES

    return {"engines": list(ENGINES.keys()), "default": "apple"}


if __name__ == "__main__":
    port = int(os.environ.get("STT_PORT", "4108"))
    uvicorn.run(app, host="127.0.0.1", port=port)
