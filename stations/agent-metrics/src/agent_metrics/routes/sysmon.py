"""Sysmon + Quota + Guardian/Sweep API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_metrics.quota_collector import get_quota, get_raw_cache
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
    return {
        "raw": raw,
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
