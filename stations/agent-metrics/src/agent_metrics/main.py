"""Agent Metrics — FastAPI application entry point.

Usage:
    python -m agent_metrics                              # Start on default port 8795
    python -m agent_metrics --port 8796                  # Custom port
    AGENT_METRICS_PORT=8796 python -m agent_metrics      # Via env var
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_metrics import __version__
from agent_metrics.config import settings
from agent_metrics.db import close_pool, get_pool
from agent_metrics.routes import router

log = structlog.get_logger()

_aggregator_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _aggregator_task

    pool = await get_pool()

    # Start session tracking aggregator background task
    from agent_metrics.aggregator import aggregator_loop

    _aggregator_task = asyncio.create_task(aggregator_loop())

    log.info(
        "starting",
        service=settings.SERVICE_NAME,
        port=settings.PORT,
        version=__version__,
        pool_size=pool.get_size(),
    )
    yield

    # Shutdown aggregator
    if _aggregator_task and not _aggregator_task.done():
        _aggregator_task.cancel()
        try:
            await _aggregator_task
        except asyncio.CancelledError:
            pass

    await close_pool()
    log.info("shutting_down", service=settings.SERVICE_NAME)


app = FastAPI(
    title="Agent Metrics API",
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

    parser = argparse.ArgumentParser(description="Agent Metrics API")
    parser.add_argument("--host", default=settings.HOST)
    parser.add_argument("--port", type=int, default=settings.PORT)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
