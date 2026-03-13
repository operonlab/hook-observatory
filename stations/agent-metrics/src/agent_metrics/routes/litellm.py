"""LiteLLM usage routes — spend tracking via ingest + DB storage."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from agent_metrics.litellm_collector import (
    generate_litellm_summary,
    get_litellm_daily_data,
    get_litellm_model_breakdown,
    get_litellm_month_to_date,
    get_litellm_status,
    ingest_litellm_usage,
    query_litellm_stats,
)

logger = logging.getLogger("agent-metrics.litellm")

router = APIRouter()


def _run_sync(fn, *args):
    """Run a sync function in the default executor."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, fn, *args)


class LiteLLMIngestRequest(BaseModel):
    """Request to ingest a LiteLLM usage record."""

    request_id: str
    model: str
    provider: str | None = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    start_time: str | None = None
    end_user_id: str | None = None
    metadata: dict | None = None


@router.get("/status")
async def litellm_status() -> dict:
    """Get LiteLLM proxy status."""
    return get_litellm_status()


@router.post("/ingest")
async def litellm_ingest(data: LiteLLMIngestRequest) -> dict:
    """Ingest a LiteLLM usage record."""
    record = {
        "request_id": data.request_id,
        "model": data.model,
        "provider": data.provider,
        "total_tokens": data.total_tokens,
        "prompt_tokens": data.prompt_tokens,
        "completion_tokens": data.completion_tokens,
        "cost_usd": data.cost_usd,
        "start_time": data.start_time,
        "end_user_id": data.end_user_id,
        "metadata": data.metadata,
    }
    success = ingest_litellm_usage(record)
    return {"success": success, "request_id": data.request_id}


@router.get("/stats")
async def litellm_stats(
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Get LiteLLM usage statistics from local DB."""
    return await _run_sync(query_litellm_stats, days)


@router.get("/summary")
async def litellm_summary(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """LiteLLM usage summary with trends."""
    return await _run_sync(generate_litellm_summary, days)


@router.get("/trends")
async def litellm_trends(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Daily cost trends from LiteLLM."""
    daily = await _run_sync(get_litellm_daily_data, days)

    running_total = 0.0
    enriched_daily = []
    for i, day in enumerate(daily):
        cost = day.get("cost_usd", 0)
        running_total += cost
        entry = {
            "date": day["date"],
            "cost_usd": cost,
            "requests": day.get("requests", 0),
            "tokens_in": day.get("tokens_in", 0),
            "tokens_out": day.get("tokens_out", 0),
            "cumulative_cost_usd": round(running_total, 4),
        }
        if i >= 6:
            window = daily[i - 6 : i + 1]
            avg = sum(d.get("cost_usd", 0) for d in window) / 7
            entry["cost_7d_avg_usd"] = round(avg, 4)
        enriched_daily.append(entry)

    days_elapsed = len(daily) or 1
    avg_daily_cost = running_total / days_elapsed
    projected_monthly = round(avg_daily_cost * 30, 2)

    return {
        "type": "litellm_trends",
        "period_days": days,
        "daily": enriched_daily,
        "summary": {
            "total_cost_usd": round(running_total, 4),
            "avg_daily_cost_usd": round(avg_daily_cost, 4),
            "projected_monthly_usd": projected_monthly,
        },
    }


@router.get("/by-model")
async def litellm_by_model(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Per-model cost breakdown from LiteLLM."""
    models = await _run_sync(get_litellm_model_breakdown, days)
    return {
        "type": "litellm_by_model",
        "period_days": days,
        "total_cost_usd": sum(m.get("cost_usd", 0) for m in models),
        "model_count": len(models),
        "models": models,
    }


@router.get("/month-to-date")
async def litellm_month_to_date() -> dict:
    """Month-to-date aggregated spend from LiteLLM."""
    return await _run_sync(get_litellm_month_to_date)
