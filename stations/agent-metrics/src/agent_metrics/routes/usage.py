"""Usage routes — subscription, budget, trends, by-model, cache.

Ported from llm-usage station. All sync subprocess calls are wrapped
in run_in_executor to keep the event loop non-blocking.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from agent_metrics.config import settings
from agent_metrics.usage_analyzer import generate_by_model, generate_summary, generate_trends
from agent_metrics.usage_collector import (
    collect_subscriptions,
    get_month_to_date,
)

router = APIRouter()


def _run_sync(fn, *args):
    """Run a sync function in the default executor."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, fn, *args)


@router.get("/summary")
async def usage_summary() -> dict:
    """Dual-track overview: subscription + API spend."""
    return await _run_sync(generate_summary)


@router.get("/trends")
async def usage_trends(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Daily cost trends with 7-day moving average and monthly projection."""
    return await _run_sync(generate_trends, days)


@router.get("/by-model")
async def usage_by_model(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Per-model cost breakdown from ccusage."""
    return await _run_sync(generate_by_model, days)


@router.get("/budget")
async def usage_budget() -> dict:
    """Monthly budget status (API spend vs budget)."""
    mtd = await _run_sync(get_month_to_date)
    budget = settings.API_MONTHLY_BUDGET_USD
    used = mtd.get("total_cost_usd", 0)
    used_pct = round(used / budget * 100, 1) if budget > 0 else 0
    warning = used_pct >= settings.BUDGET_WARNING_PCT
    return {
        "budget_usd": budget,
        "used_usd": used,
        "used_pct": used_pct,
        "remaining_usd": round(budget - used, 2),
        "warning": warning,
        "warning_threshold_pct": settings.BUDGET_WARNING_PCT,
        "days_elapsed": mtd.get("days", 0),
    }


@router.get("/cache")
async def usage_cache() -> dict:
    """Cache efficiency stats for current month."""
    mtd = await _run_sync(get_month_to_date)
    return {
        "cache_hit_rate": mtd.get("cache_hit_rate", 0),
        "total_cache_read": mtd.get("total_cache_read", 0),
        "total_cache_creation": mtd.get("total_cache_creation", 0),
        "estimated_savings_usd": mtd.get("estimated_cache_savings_usd", 0),
        "total_tokens_in": mtd.get("total_tokens_in", 0),
        "total_tokens_out": mtd.get("total_tokens_out", 0),
    }


@router.get("/subscription")
async def usage_subscription() -> dict:
    """Subscription status for all CLI providers."""
    return await _run_sync(collect_subscriptions)
