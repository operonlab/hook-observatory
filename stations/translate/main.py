"""Translate Station — Translation Proxy Service.

DeepL → Google Translate cascading with PostgreSQL cache.
Port 10205.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

# Ensure station root is on sys.path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from workshop.station_bootstrap import setup_cors, setup_logging

from config import config
from db import close_db, init_db
from routes import router

logger = setup_logging("translate")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init PostgreSQL schema. Shutdown: close connections."""
    try:
        await init_db()
    except Exception as e:
        logger.warning("Database init failed (degraded): %s", e)

    logger.info("Translate ready on %s:%d", config.host, config.port)
    yield

    await close_db()
    logger.info("Translate shutdown")


app = FastAPI(title="Translate Station", version="0.2.0", lifespan=lifespan)
setup_cors(app)
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host=config.host, port=config.port)
