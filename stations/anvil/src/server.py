"""Anvil Station -- FastAPI app for skill lifecycle management."""

from __future__ import annotations

from contextlib import asynccontextmanager

from db import Base, engine
from fastapi import FastAPI
from sqlalchemy import text
from sdk_client.station_bootstrap import setup_cors, setup_logging

from config import config
from routes import router

logger = setup_logging("anvil")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create schema + tables. Shutdown: dispose engine."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS anvil"))
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database schema ready (anvil)")

    yield

    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Anvil Station",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS -- allow workbench and local origins
setup_cors(app, mode="restricted", extra_origins=["http://localhost:4102"])

# Mount routes
app.include_router(router)


def cli():
    """Entry point for `uv run anvil-server`."""
    import uvicorn

    uvicorn.run(
        "server:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
