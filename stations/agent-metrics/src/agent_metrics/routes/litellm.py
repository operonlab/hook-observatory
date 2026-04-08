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


# ── Model Catalog (Smart / Fast / Value per provider) ──────────

_MODEL_CATALOG = [
    {
        "provider": "GLM (Z.AI)",
        "provider_key": "zhipu",
        "smart": {"name": "glm-5", "price": "$1.00/$3.20", "note": ""},
        "fast": {"name": "glm-5-turbo", "price": "$1.00/$3.20", "note": "推理加速"},
        "value": {"name": "glm-4.5-air", "price": "$0.20/$1.10", "note": "便宜好用"},
    },
    {
        "provider": "Kimi (Moonshot)",
        "provider_key": "moonshot",
        "smart": {"name": "kimi-k2.5", "price": "$0.60/$3.00", "note": "旗艦多模態"},
        "fast": {"name": "kimi-k2-turbo", "price": "$1.15/$8.00", "note": "60-100 tok/s"},
        "value": {"name": "kimi-k2-thinking", "price": "$0.47/$2.00", "note": "深度推理便宜"},
    },
    {
        "provider": "MiniMax",
        "provider_key": "minimax",
        "smart": {"name": "minimax-m2.7", "price": "$0.30/$1.20", "note": "最新旗艦"},
        "fast": {"name": "minimax-m2.7-hs", "price": "$0.60/$2.40", "note": "高速推理"},
        "value": {"name": "minimax-m2.5", "price": "$0.30/$1.20", "note": "穩定成熟"},
    },
    {
        "provider": "DeepSeek",
        "provider_key": "deepseek",
        "smart": {"name": "deepseek-r1", "price": "$0.28/$0.42", "note": "最強推理"},
        "fast": {"name": "deepseek-v3", "price": "$0.28/$0.42", "note": "地表最便宜"},
        "value": {"name": "deepseek-v3", "price": "$0.28/$0.42", "note": "Fast+Value 同一模型"},
    },
    {
        "provider": "Grok (xAI)",
        "provider_key": "xai",
        "smart": {"name": "grok-4.20", "price": "$2.00/$6.00", "note": "2M context 旗艦"},
        "fast": {"name": "grok-4.1-fast", "price": "$0.20/$0.50", "note": "非推理極速"},
        "value": {"name": "grok-4.1-value", "price": "$0.20/$0.50", "note": "推理能力+便宜"},
    },
    {
        "provider": "Qwen (阿里)",
        "provider_key": "dashscope",
        "smart": {"name": "qwen3-max", "price": "$1.20/$6.00", "note": "最強推理"},
        "fast": {"name": "qwen3.5-flash", "price": "$0.10/$0.40", "note": "極速低成本"},
        "value": {"name": "qwen3.5-122b", "price": "$0.40/$3.20", "note": "開源大模型 CP 王"},
    },
    {
        "provider": "Gemini (Google)",
        "provider_key": "google",
        "smart": {"name": "gemini-3.1-pro", "price": "$2.00/$12.00", "note": "旗艦推理"},
        "fast": {"name": "gemini-3.1-flash-lite", "price": "$0.25/$1.50", "note": "極速"},
        "value": {"name": "gemini-2.5-flash", "price": "免費/低價", "note": "品質速度均衡"},
    },
]


_HIGHLIGHTS_SUBJECTIVE = {
    "smart": {"name": "grok-4.20", "provider": "xAI", "note": "2M context 旗艦，config 標註最強"},
    "fast": {"name": "qwen3.5-flash", "provider": "Qwen", "note": "$0.10/$0.40 全場最低 input 價"},
    "value": {"name": "deepseek-v3", "provider": "DeepSeek", "note": "$0.28/$0.42 地板價"},
    "free": {
        "name": "gemini-2.5-flash",
        "provider": "Google",
        "note": "仍免費，但 2025/12 速率限制砍半",
    },
}

# Sources: LMSYS Chatbot Arena (2026-04-07), SWE-Bench Verified, ArtificialAnalysis.ai
_HIGHLIGHTS_BENCHMARK = {
    "overall": {
        "name": "grok-4.20",
        "provider": "xAI",
        "score": "1491 Elo",
        "note": "LiteLLM 最強（全域 #3，#1/#2 為御三家）",
        "configured": True,
    },
    "coding": {
        "name": "grok-4.20",
        "provider": "xAI",
        "score": "79.6% SWE-Bench",
        "note": "亞軍 gemini-3.1-pro 78.8%",
        "configured": True,
    },
    "reasoning": {
        "name": "kimi-k2.5",
        "provider": "Moonshot",
        "score": "96.1% AIME",
        "note": "數學推理遙遙領先",
        "configured": True,
    },
    "chinese": {
        "name": "glm-5",
        "provider": "Z.AI",
        "score": "1456 Elo",
        "note": "開源中文模型王，BenchLM 82",
        "configured": True,
    },
    "speed": {
        "name": "gemini-2.5-flash-lite",
        "provider": "Google",
        "score": "380 tok/s",
        "note": "全場最快出字速度",
        "configured": True,
    },
    "cost": {
        "name": "deepseek-v3",
        "provider": "DeepSeek",
        "score": "$0.28/M in",
        "note": "品質/價格比最高",
        "configured": True,
    },
}

# 未設定但值得關注的模型（排除御三家 Anthropic/OpenAI/Google + 已設定 provider）
_NOTABLE_UNCONFIGURED = [
    {
        "name": "mistral-large-3",
        "provider": "Mistral AI",
        "score": "~1460 Elo",
        "strengths": "性價比最佳中端，多平台部署（Bedrock/Azure/OpenRouter）",
        "access": "Mistral API / OpenRouter",
        "price": "$2.00/$6.00",
    },
    {
        "name": "llama-3.1-405b",
        "provider": "Meta（開源）",
        "score": "開源最強",
        "strengths": "完全開源，Fireworks/Together/DeepInfra 均可用",
        "access": "Fireworks / Together.ai",
        "price": "$0.80~1.50/M",
    },
    {
        "name": "reka-core",
        "provider": "Reka AI",
        "score": "MMLU 83.2",
        "strengths": "多模態（視覺）強，HumanEval 76.8%，128K context",
        "access": "Reka API + SDK",
        "price": "~$2~3/M in",
    },
    {
        "name": "doubao-2.0",
        "provider": "ByteDance",
        "score": "中文頂級",
        "strengths": "日活 1 億+，中文消費級最強，2026 新版",
        "access": "豆包 API（中國區）",
        "price": "~¥0.008/千 tokens",
    },
    {
        "name": "mistral-nemo",
        "provider": "Mistral AI",
        "score": "1160 Elo",
        "strengths": "預算級最佳，推理極快，$0.10~0.20/M",
        "access": "Fireworks / Together.ai",
        "price": "$0.10/$0.20",
    },
    {
        "name": "command-r-plus",
        "provider": "Cohere",
        "score": "企業級",
        "strengths": "RAG 優化，企業穩定性，生產就緒",
        "access": "Cohere API",
        "price": "$2.50/$10.00",
    },
]

_SCENARIOS = [
    {
        "task": "寫程式",
        "best": "grok-4.20",
        "alt": "gemini-3.1-pro",
        "reason": "SWE-Bench 79.6% / 78.8%",
    },
    {"task": "中文內容", "best": "glm-5", "alt": "kimi-k2.5", "reason": "Arena 1456 / ~1450 Elo"},
    {
        "task": "數學推理",
        "best": "kimi-k2.5",
        "alt": "deepseek-r1",
        "reason": "AIME 96.1%，K2.5 數學最強",
    },
    {
        "task": "研究分析",
        "best": "gemini-3.1-pro",
        "alt": "grok-4.20",
        "reason": "Intelligence 57，長文理解佳",
    },
    {
        "task": "快速草稿",
        "best": "qwen3.5-flash",
        "alt": "gemini-3.1-flash-lite",
        "reason": "$0.10 + 極速出字",
    },
    {
        "task": "Agent 任務",
        "best": "kimi-k2.5",
        "alt": "minimax-m2.7",
        "reason": "BrowseComp 78%，多步工具使用",
    },
    {
        "task": "省錢至上",
        "best": "deepseek-v3",
        "alt": "qwen3.5-flash",
        "reason": "$0.28/$0.42 vs $0.10/$0.40",
    },
]


def _get_dynamic_catalog() -> dict | None:
    """Read full catalog from Redis (weekly sync). Returns None if unavailable."""
    try:
        import redis

        from agent_metrics.config import settings

        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        cached = r.get("agent-metrics:model-catalog:full")
        if cached:
            import json

            return json.loads(cached)
    except Exception:
        pass
    return None


@router.get("/model-catalog")
async def litellm_model_catalog() -> dict:
    """Return model catalog — Redis dynamic data with hardcoded fallback."""
    dynamic = _get_dynamic_catalog()

    if dynamic:
        return {
            "catalog": _MODEL_CATALOG,
            "highlights_subjective": dynamic.get("highlights_subjective", _HIGHLIGHTS_SUBJECTIVE),
            "highlights_benchmark": dynamic.get("highlights_benchmark", _HIGHLIGHTS_BENCHMARK),
            "notable_unconfigured": {
                "models": dynamic.get("notable_unconfigured", _NOTABLE_UNCONFIGURED),
                "synced_at": dynamic.get("synced_at"),
            },
            "scenarios": dynamic.get("scenarios", _SCENARIOS),
            "synced_at": dynamic.get("synced_at"),
            "data_sources": {
                "arena": f"LMSYS Chatbot Arena ({dynamic.get('synced_at', '?')[:10]})",
                "swe_bench": "SWE-Bench Verified (vals.ai)",
                "speed": "ArtificialAnalysis.ai (72h rolling avg)",
            },
        }

    # Fallback to hardcoded
    return {
        "catalog": _MODEL_CATALOG,
        "highlights_subjective": _HIGHLIGHTS_SUBJECTIVE,
        "highlights_benchmark": _HIGHLIGHTS_BENCHMARK,
        "notable_unconfigured": {
            "models": _NOTABLE_UNCONFIGURED,
            "synced_at": "2026-04-08T08:00:00Z",
        },
        "scenarios": _SCENARIOS,
        "synced_at": None,
        "data_sources": {
            "arena": "LMSYS Chatbot Arena (2026-04-07, hardcoded)",
            "swe_bench": "SWE-Bench Verified (vals.ai)",
            "speed": "ArtificialAnalysis.ai (72h rolling avg)",
        },
    }
