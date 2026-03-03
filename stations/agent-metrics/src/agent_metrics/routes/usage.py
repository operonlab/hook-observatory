"""Usage routes — subscription, budget, trends, by-model, cache.

Ported from llm-usage station. All sync subprocess calls are wrapped
in run_in_executor to keep the event loop non-blocking.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query

from agent_metrics.config import settings
from agent_metrics.usage_analyzer import generate_by_model, generate_summary, generate_trends
from agent_metrics.usage_collector import (
    collect_subscriptions,
    get_month_to_date,
)

logger = logging.getLogger("agent-metrics.usage")

# Track whether we've already pushed a budget warning this month
_budget_warning_pushed = False

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
    global _budget_warning_pushed
    mtd = await _run_sync(get_month_to_date)
    budget = settings.API_MONTHLY_BUDGET_USD
    used = mtd.get("total_cost_usd", 0)
    used_pct = round(used / budget * 100, 1) if budget > 0 else 0
    warning = used_pct >= settings.BUDGET_WARNING_PCT

    # Push notification once per month when budget warning threshold is hit
    if warning and not _budget_warning_pushed:
        _budget_warning_pushed = True
        await _push_budget_warning(used_pct, used, budget)

    return {
        "budget_usd": budget,
        "used_usd": used,
        "used_pct": used_pct,
        "remaining_usd": round(budget - used, 2),
        "warning": warning,
        "warning_threshold_pct": settings.BUDGET_WARNING_PCT,
        "days_elapsed": mtd.get("days", 0),
    }


async def _push_budget_warning(used_pct: float, used: float, budget: float) -> None:
    """Publish budget warning to Redis workshop:push channel."""
    import redis.asyncio as aioredis

    payload = {
        "category": "agent",
        "title": f"LLM 用量警告: {used_pct}%",
        "body": f"本月已使用 ${used:.2f} / ${budget:.2f}",
        "url": "/v2/apps/agent-metrics/",
        "tag": "agent-budget-monthly",
        "severity": "warning",
    }
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.publish("workshop:push", json.dumps(payload, ensure_ascii=False))
        await r.aclose()
    except Exception as e:
        logger.warning("Failed to publish budget warning: %s", e)


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
