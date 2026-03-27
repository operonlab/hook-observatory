"""Paper Service — standalone FastAPI microservice (POC).

Extracted from core/src/modules/paper/ for multi-machine deployment.
Connects to shared PostgreSQL + Redis via environment variables.

Usage:
    PAPER_DB_URL=postgresql://...@100.x.x.x/workshop \
    python -m uvicorn src.main:app --host 0.0.0.0 --port 10010
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import close_db, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Paper Service started on port %s", settings.port)
    yield
    await close_db()
    logger.info("Paper Service shut down")


app = FastAPI(
    title="Paper Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "paper-svc", "version": "0.1.0"}


# TODO: Import and mount paper routes once shared dependencies are extracted
# from src.modules.paper.routes import router as paper_router
# app.include_router(paper_router, prefix="/api/paper")


# For now, a placeholder that confirms DB connectivity
@app.get("/api/paper/status")
async def paper_status():
    from sqlalchemy import text

    from src.database import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM paper.articles"))
        count = result.scalar()
    return {"articles": count, "service": "paper-svc"}
