"""LiteLLM Usage Collector — proxy health/model info + Redis-backed provider quotas.

Historical context: Earlier versions queried `litellm_spend.spend_logs` directly via
psycopg, but LiteLLM proxy lacks the prisma extras and that table is empty.
HTTP endpoints `/customer/info` etc. all return DB-not-connected errors.
The only live data sources are:
1. LiteLLM proxy `/health/liveliness` and `/model/info`
2. Redis keys written by `ws_provider_balance_sync.py` (provider balances)
3. Hardcoded fallback for provider balance defaults
"""

from __future__ import annotations

import json
import logging
import urllib.request

from agent_metrics.config import settings

logger = logging.getLogger("agent-metrics.litellm")


def _litellm_request(path: str, method: str = "GET", data: dict | None = None) -> dict | None:
    """Make a request to LiteLLM API."""
    url = f"{settings.LITELLM_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}",
        "Accept": "application/json",
    }

    try:
        if method == "POST" and data:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = urllib.request.Request(url, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug(f"LiteLLM API error ({path}): {e}")
        return None


def get_litellm_status() -> dict:
    """Get LiteLLM proxy status and configured model list."""
    result = {"proxy_alive": False, "models_configured": [], "error": None}
    try:
        req = urllib.request.Request(f"{settings.LITELLM_BASE_URL}/health/liveliness")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result["proxy_alive"] = resp.status == 200
    except Exception as e:
        result["error"] = f"Proxy unreachable: {e}"
        return result

    data = _litellm_request("/model/info")
    if data:
        models = data.get("data", [])
        result["models_configured"] = [m.get("model_name", "?") for m in models]
    return result


# 額度預設值 (Redis 無資料時的 fallback)
# key = 模型提供商 (非模型名稱)
_DEFAULT_QUOTAS = {
    "minimax": {"total": 25.0, "remaining": 24.24},
    "moonshot": {"total": 25.0, "remaining": 23.67811},
    "zhipu": {"total": 10.0, "remaining": 10.0},
    "deepseek": {"total": 12.0, "remaining": 10.25},
    "dashscope": {"total": 0.0, "remaining": 0.0},  # 免費額度 (token制)，無儲值
    "xai": {"total": 25.0, "remaining": 25.0},
    "google": {
        "total": 635.0,
        "remaining": 549.35,
    },  # Google Cloud 抵免額 (2x CREDIT_TYPE_MONTHLY, 可使用 only)
}

_PROVIDER_REDIS_PREFIX = "agent-metrics:provider"
DASHSCOPE_FREE_QUOTA_REDIS_KEY = "agent-metrics:dashscope:free_quota"
DASHSCOPE_FREE_QUOTA_DEFAULTS = {
    "total_models": 95,
    "healthy": 90,
    "over_50pct": 0,
    "over_80pct": 0,
    "no_free": 5,
    "top_models": [
        {"model": "qwen3-max", "remaining": 999961, "total": 1000000},
        {"model": "qwen-max", "remaining": 999984, "total": 1000000},
        {"model": "qwen3.5-122b-a10b", "remaining": 1000000, "total": 1000000},
    ],
}


def _get_provider_quotas() -> dict:
    """取得各供應商額度：Redis 優先（ws_provider_balance_sync.py 定期更新），fallback 到預設值。"""
    quotas = dict(_DEFAULT_QUOTAS)
    try:
        import redis as _redis

        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        for name in ("minimax", "moonshot", "zhipu", "deepseek", "xai", "google"):
            cached = r.get(f"{_PROVIDER_REDIS_PREFIX}:{name}:balance")
            if cached:
                data = json.loads(cached)
                quotas[name] = {
                    "total": data.get("total", quotas[name]["total"]),
                    "remaining": data.get("remaining", quotas[name]["remaining"]),
                }
    except Exception:
        pass
    return quotas


def get_dashscope_free_quota() -> dict:
    """取得 DashScope (Qwen) 免費額度資訊：Redis 優先，fallback 到預設值。"""
    try:
        import redis as _redis

        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        cached = r.get(DASHSCOPE_FREE_QUOTA_REDIS_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return DASHSCOPE_FREE_QUOTA_DEFAULTS


def get_litellm_manual_summary():
    """回傳各供應商額度總計 + Qwen 免費額度（Redis 即時資料優先）。"""
    quotas = _get_provider_quotas()
    total_budget = sum(q["total"] for q in quotas.values())
    total_remaining = sum(q["remaining"] for q in quotas.values())
    total_spent = total_budget - total_remaining

    breakdown = []
    for name, q in quotas.items():
        entry = {
            "name": name,
            "total": q["total"],
            "remaining": q["remaining"],
            "spent": round(q["total"] - q["remaining"], 4),
            "pct": round((q["total"] - q["remaining"]) / q["total"] * 100, 1)
            if q["total"] > 0
            else 0,
        }
        if name == "dashscope":
            fq = get_dashscope_free_quota()
            entry["free_quota"] = fq
            entry["note"] = f"免費額度 {fq['total_models']} 模型，各 1M tokens"
        elif name == "google":
            entry["note"] = "Google Cloud 抵免額"
        breakdown.append(entry)

    return {
        "total_budget_usd": total_budget,
        "total_remaining_usd": total_remaining,
        "total_spent_usd": round(total_spent, 4),
        "breakdown": breakdown,
        "dashscope_free_quota": get_dashscope_free_quota(),
    }
