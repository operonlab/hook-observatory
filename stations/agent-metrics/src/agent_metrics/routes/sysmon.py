"""Sysmon + Quota + Guardian/Sweep API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_metrics.sysmon_loop import get_history, get_latest

router = APIRouter()


# ---------------------------------------------------------------------------
# System Metrics
# ---------------------------------------------------------------------------

@router.get("/sysmon/current")
async def sysmon_current():
    """Return the latest system metrics snapshot."""
    data = get_latest()
    if not data:
        return {"error": "no data yet"}
    return data


@router.get("/sysmon/history")
async def sysmon_history(minutes: int = Query(default=60, ge=1, le=720)):
    """Return sysmon history from ring buffer."""
    return {"entries": get_history(minutes), "interval_s": 5}
