"""TPS Station — Translation Proxy Service.

DeepL → Google Translate cascading with Redis cache.
Port 4114.
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

from cache import close_redis, get_redis
from config import config
from routes import router

logger = setup_logging("tps")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify Redis. Shutdown: close connections."""
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis unavailable (cache degraded): %s", e)

    logger.info("TPS ready on %s:%d", config.host, config.port)
    yield

    await close_redis()
    logger.info("TPS shutdown")


app = FastAPI(title="TPS Station", version="0.1.0", lifespan=lifespan)
setup_cors(app)
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host=config.host, port=config.port)
