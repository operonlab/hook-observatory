"""Video Edit — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from video_edit import __version__
from video_edit.config import settings
from video_edit.mlt_engine import MLTEngine
from video_edit.routes import router

log = structlog.get_logger()

# Shared engine instance
engine = MLTEngine()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "starting",
        service=settings.SERVICE_NAME,
        port=settings.PORT,
        version=__version__,
    )
    yield
    log.info("shutting_down", service=settings.SERVICE_NAME)


app = FastAPI(
    title="Video Edit API",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME, "version": __version__}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Video Edit API")
    parser.add_argument("--host", default=settings.HOST)
    parser.add_argument("--port", type=int, default=settings.PORT)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
