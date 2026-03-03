"""AgentOps — FastAPI application entry point.

Usage:
    python -m agentops                     # Start on default port 8795
    python -m agentops --port 8796         # Custom port
    AGENTOPS_PORT=8796 python -m agentops  # Via env var
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentops import __version__
from agentops.config import settings
from agentops.db import close_pool, get_pool
from agentops.routes import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    pool = await get_pool()
    log.info(
        "starting",
        service=settings.SERVICE_NAME,
        port=settings.PORT,
        version=__version__,
        pool_size=pool.get_size(),
    )
    yield
    await close_pool()
    log.info("shutting_down", service=settings.SERVICE_NAME)


app = FastAPI(
    title="AgentOps API",
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

    parser = argparse.ArgumentParser(description="AgentOps API")
    parser.add_argument("--host", default=settings.HOST)
    parser.add_argument("--port", type=int, default=settings.PORT)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
