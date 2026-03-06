"""Sysmon + Quota + Guardian/Sweep API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_metrics.db import get_pool
from agent_metrics.quota_collector import (
    get_quota,
    get_quota_health,
    get_raw_cache,
    reset_cc_backoff,
)
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


# ---------------------------------------------------------------------------
# LLM Quota
# ---------------------------------------------------------------------------


@router.get("/quota/current")
async def quota_current():
    """Return raw + parsed quota data for all LLM providers."""
    quota = await get_quota()
    raw = get_raw_cache()
    health = get_quota_health()
    return {
        "raw": raw,
        "health": health,
        "parsed": {
            "cc": quota.get("cc_parsed", {}),
            "cx": quota.get("cx_parsed", {}),
            "gm": quota.get("gm_parsed", {}),
        },
        "formatted": {
            "cc_5h": quota.get("llm_cc_5h", "?"),
            "cc_7d": quota.get("llm_cc_7d", "?"),
            "cc_ex": quota.get("llm_cc_ex", "?"),
            "cx_5h": quota.get("llm_cx_5h", "?"),
            "cx_7d": quota.get("llm_cx_7d", "?"),
            "gm_pro": quota.get("llm_gm_pro", "?"),
            "gm_flash": quota.get("llm_gm_flash", "?"),
        },
    }


@router.get("/quota/formatted")
async def quota_formatted():
    """Return tmux-compatible formatted quota strings."""
    quota = await get_quota()
    return {
        "cc-5h": quota.get("llm_cc_5h", "?"),
        "cc-7d": quota.get("llm_cc_7d", "?"),
        "cc-ex": quota.get("llm_cc_ex", "?"),
        "cx-5h": quota.get("llm_cx_5h", "?"),
        "cx-7d": quota.get("llm_cx_7d", "?"),
        "gm-pro": quota.get("llm_gm_pro", "?"),
        "gm-flash": quota.get("llm_gm_flash", "?"),
        "display": quota.get("llm_display", "?"),
    }


@router.post("/quota/reset-cc-backoff")
async def quota_reset_cc_backoff():
    """Reset CC backoff and force a fresh fetch on next tick."""
    reset_cc_backoff()
    quota = await get_quota(force=True)
    health = get_quota_health()
    return {
        "action": "backoff_reset",
        "health": health.get("cc", {}),
        "cc_5h": quota.get("llm_cc_5h", "?"),
        "cc_7d": quota.get("llm_cc_7d", "?"),
    }


# ---------------------------------------------------------------------------
# Guardian / Sweep Logs
# ---------------------------------------------------------------------------


@router.get("/guardian/log")
async def guardian_log(
    hours: int = Query(default=24, ge=1, le=168),
    level: str | None = Query(default=None),
):
    """Return guardian action log."""
    pool = await get_pool()
    query = (
        "SELECT id, ts, level, priority, pid, process_name, mem_mb, cpu_pct, "
        "action, result, detail FROM guardian_actions "
        "WHERE ts > now() - make_interval(hours => $1) AND level != 'SWEEP'"
    )
    params: list = [hours]
    if level:
        query += " AND level = $2"
        params.append(level)
    query += " ORDER BY ts DESC LIMIT 200"

    rows = await pool.fetch(query, *params)
    actions = [dict(r) for r in rows]
    for a in actions:
        if a.get("ts"):
            a["ts"] = a["ts"].isoformat()
    return {"actions": actions, "total": len(actions)}


@router.get("/sweep/log")
async def sweep_log(hours: int = Query(default=24, ge=1, le=168)):
    """Return sweep action log."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, ts, level, priority, pid, process_name, mem_mb, cpu_pct, "
        "action, result, detail FROM guardian_actions "
        "WHERE ts > now() - make_interval(hours => $1) AND level = 'SWEEP' "
        "ORDER BY ts DESC LIMIT 200",
        hours,
    )
    actions = [dict(r) for r in rows]
    for a in actions:
        if a.get("ts"):
            a["ts"] = a["ts"].isoformat()
    return {"actions": actions, "total": len(actions)}
