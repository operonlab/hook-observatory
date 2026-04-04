"""Hook Observatory — FastAPI app with spool-based event ingestion."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from database import IS_POSTGRES, async_session, engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import Base, HookEvent
from spool import SpoolDrainer
from sqlalchemy import text

from config import config
from routes import router
from sdk_client.station_bootstrap import setup_logging

logger = setup_logging("hook-observatory")

_drainer: SpoolDrainer | None = None


def _strip_null(obj):
    """Recursively strip \\u0000 null bytes from strings (PostgreSQL rejects them)."""
    if isinstance(obj, str):
        return obj.replace("\x00", "").replace("\\u0000", "")
    if isinstance(obj, dict):
        return {k: _strip_null(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null(v) for v in obj]
    return obj


def _build_rows(events: list[dict]) -> list[dict]:
    """Convert raw spool events to DB row dicts."""
    rows = []
    for evt in events:
        data = _strip_null(evt.get("data", {})) if IS_POSTGRES else evt.get("data", {})
        rows.append(
            {
                "event_type": evt.get("event_type", "unknown"),
                "session_id": data.get("session_id"),
                "cwd": data.get("cwd"),
                "tool_name": data.get("tool_name"),
                "hook_name": data.get("hook_name"),
                "payload": data,
                "dedup_hash": evt.get("_dedup_hash", ""),
            }
        )
    return rows


async def _batch_write_pg(events: list[dict]) -> None:
    """PostgreSQL: bulk INSERT ... ON CONFLICT DO NOTHING."""
    import asyncio

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not events:
        return
    async with async_session() as session:
        stmt = pg_insert(HookEvent).values(_build_rows(events))
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_hash"])
        await asyncio.wait_for(session.execute(stmt), timeout=30)
        await asyncio.wait_for(session.commit(), timeout=30)


async def _batch_write_sqlite(events: list[dict]) -> None:
    """SQLite: INSERT OR IGNORE (dedup via unique index)."""
    import asyncio

    from sqlalchemy import insert

    if not events:
        return
    async with async_session() as session:
        rows = _build_rows(events)
        # Add Python-generated defaults for SQLite
        from models import _make_uuid, _utcnow

        for row in rows:
            row["id"] = _make_uuid()
            row["created_at"] = _utcnow()
            if row["payload"] is None:
                row["payload"] = {}

        stmt = insert(HookEvent).prefix_with("OR IGNORE").values(rows)
        await asyncio.wait_for(session.execute(stmt), timeout=30)
        await asyncio.wait_for(session.commit(), timeout=30)


_batch_write_events = _batch_write_pg if IS_POSTGRES else _batch_write_sqlite


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create schema + tables, start spool drainer."""
    global _drainer

    async with engine.begin() as conn:
        if IS_POSTGRES:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS hook_observatory"))
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database ready (%s)", "PostgreSQL" if IS_POSTGRES else "SQLite")

    # Wire reactive store
    from store import hook_store

    app.state.store = hook_store

    # Start spool drainer
    _drainer = SpoolDrainer(
        spool_dir=config.spool_dir,
        drain_interval=config.spool.drain_interval,
        batch_size=config.spool.batch_size,
    )
    await _drainer.start(_batch_write_events)

    yield

    # Shutdown
    if _drainer:
        await _drainer.stop()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Hook Observatory",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow workbench origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:10100",
        "https://workshop.joneshong.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(router)

# Serve frontend SPA with fallback to index.html for client-side routes.
frontend_dir = Path(__file__).parent / "frontend" / "dist"
if frontend_dir.exists():
    _index_html = frontend_dir / "index.html"

    @app.middleware("http")
    async def spa_fallback(request, call_next):
        resp = await call_next(request)
        # Non-API path got 404 → serve index.html for SPA routing
        if resp.status_code == 404 and not request.url.path.startswith("/api"):
            from starlette.responses import FileResponse

            return FileResponse(_index_html, media_type="text/html")
        return resp

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="spa")


def cli():
    """Entry point for `uv run hook-observatory`."""
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
