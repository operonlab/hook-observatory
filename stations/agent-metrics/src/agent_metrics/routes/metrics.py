"""Session tracking routes — ingest, current, sessions, history.

Ported from V1 with Redis cache removed (single-process in-memory is sufficient)
and sync DB calls replaced by asyncpg.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException

from agent_metrics import session_store
from agent_metrics.db import get_pool
from agent_metrics.file_fallback import read_fallback, write_fallback
from agent_metrics.models import IngestRequest, IngestResponse

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest) -> IngestResponse:
    """Process a statusline update. Returns backward-compatible {total, sessions, daily}."""
    result = await session_store.ingest(req)

    # Write file fallback asynchronously (non-blocking)
    snapshot = await session_store.get_snapshot()
    asyncio.get_running_loop().run_in_executor(None, write_fallback, snapshot)

    return IngestResponse(**result)


@router.get("/current")
async def current() -> dict:
    """Return current daily summary + active sessions (from memory or file fallback)."""
    # Primary: in-memory (fastest, always fresh)
    snapshot = await session_store.get_snapshot()
    if snapshot.get("sessions"):
        return snapshot

    # Fallback: file
    fb = read_fallback()
    if fb:
        return fb

    return {"date": "", "total_cost_usd": 0, "active_sessions": 0, "sessions": []}


@router.get("/sessions")
async def list_sessions(active_only: bool = True) -> dict:
    """List sessions. By default only active ones."""
    if active_only:
        sessions = await session_store.get_active_sessions()
        return {"sessions": sessions, "count": len(sessions)}

    # From DB for historical sessions
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM sessions ORDER BY last_seen DESC LIMIT 100"
    )
    return {
        "sessions": [dict(r) for r in rows],
        "count": len(rows),
    }


@router.get("/sessions/{sid}")
async def get_session(sid: str, snapshots: bool = False) -> dict:
    """Get session detail, optionally with snapshot history."""
    # Check in-memory first
    for s in await session_store.get_active_sessions():
        if s["sid"] == sid or s["id"].startswith(sid):
            result = {"session": s}
            if snapshots:
                result["snapshots"] = await _get_session_snapshots(s["id"])
            return result

    # Check DB
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM sessions WHERE sid = $1 OR id LIKE $2",
        sid,
        f"{sid}%",
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Session {sid} not found")
    result = {"session": dict(row)}
    if snapshots:
        result["snapshots"] = await _get_session_snapshots(row["id"])
    return result


async def _get_session_snapshots(session_id: str) -> list[dict]:
    """Get snapshot history for a session from DB."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM snapshots WHERE session_id = $1 ORDER BY ts DESC LIMIT 1000",
        session_id,
    )
    return [dict(r) for r in rows]


@router.get("/history")
async def history(days: int = 7) -> dict:
    """Return daily summaries for the past N days."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date()
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM daily_summary WHERE date >= $1 ORDER BY date DESC",
        cutoff,
    )
    return {
        "days": days,
        "summaries": [dict(r) for r in rows],
        "count": len(rows),
    }
