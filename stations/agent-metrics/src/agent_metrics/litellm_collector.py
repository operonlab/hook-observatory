"""LiteLLM Usage Collector — spend tracking via real LiteLLM DB + API.

Collects API usage data by:
1. LiteLLM Proxy DB (litellm_spend) — real usage logs
2. LiteLLM Proxy API (/customer/info) — real budget/balance
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from agent_metrics.config import settings

logger = logging.getLogger("agent-metrics.litellm")


# ── DB Helpers ──────────────────────────────────────────────────


def _get_litellm_db_connection() -> psycopg.Connection | None:
    """Get connection to the REAL LiteLLM PostgreSQL."""
    try:
        conn = psycopg.connect(settings.LITELLM_DATABASE_URL, row_factory=dict_row)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to LiteLLM DB: {e}")
        return None


# ── Helpers ─────────────────────────────────────────────────────


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


def _extract_provider(model_name: str) -> str:
    """Extract provider from LiteLLM model name."""
    model_lower = model_name.lower()
    provider_map = {
        "glm": "z.ai",
        "kimi": "moonshot",
        "minimax": "minimax",
        "deepseek": "deepseek",
        "qwen": "alibaba",
        "grok": "xai",
        "claude": "anthropic",
        "gpt": "openai",
        "llama": "meta",
        "mistral": "mistral",
    }
    for key, provider in provider_map.items():
        if key in model_lower:
            return provider
    return model_name.split("/")[0] if "/" in model_name else "unknown"


# ── Data Collection ─────────────────────────────────────────────


def get_litellm_status() -> dict:
    """Get LiteLLM proxy status and model info."""
    result = {"proxy_alive": False, "models_configured": [], "error": None}
    try:
        req = urllib.request.Request(f"{settings.LITELLM_BASE_URL}/health/liveliness", timeout=5)
        with urllib.request.urlopen(req) as resp:
            result["proxy_alive"] = resp.status == 200
    except Exception as e:
        result["error"] = f"Proxy unreachable: {e}"
        return result

    data = _litellm_request("/model/info")
    if data:
        models = data.get("data", [])
        result["models_configured"] = [m.get("model_name", "?") for m in models]
    return result


def get_litellm_customer_info(end_user_id: str = "default") -> dict | None:
    """Get real balance/budget info from LiteLLM for a customer."""
    return _litellm_request(f"/customer/info?end_user_id={end_user_id}")


def get_litellm_month_to_date() -> dict:
    """Get real month-to-date spend from LiteLLM API and DB."""
    info = get_litellm_customer_info()
    if info and "total_spend" in info:
        return {
            "requests": info.get("total_events", 0),
            "total_cost_usd": round(info.get("total_spend", 0.0), 4),
            "max_budget": info.get("max_budget"),
            "remaining_budget": info.get("budget_left", 0.0),
        }

    stats = query_litellm_stats(days=30)
    return stats.get(
        "month_to_date",
        {
            "requests": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        },
    )


def get_litellm_model_breakdown(days: int = 30) -> list[dict]:
    """Get per-model spend breakdown from LiteLLM REAL DB."""
    conn = _get_litellm_db_connection()
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
            cur.execute(
                """
                SELECT
                    model,
                    COUNT(*) as requests,
                    SUM(response_cost) as cost_usd,
                    SUM(total_tokens) as total_tokens
                FROM spend_logs
                WHERE start_time >= %s
                GROUP BY model
                ORDER BY cost_usd DESC
            """,
                (start_date,),
            )

            rows = cur.fetchall()
            total_cost = sum(float(row["cost_usd"] or 0) for row in rows)

            result = []
            for row in rows:
                cost = float(row["cost_usd"] or 0)
                result.append(
                    {
                        "model": row["model"],
                        "provider": _extract_provider(row["model"]),
                        "requests": row["requests"] or 0,
                        "cost_usd": round(cost, 4),
                        "total_tokens": row["total_tokens"] or 0,
                        "pct_of_total": round(cost / total_cost * 100, 1) if total_cost > 0 else 0,
                    }
                )
            return result
    except Exception as e:
        logger.error(f"Failed to fetch model breakdown: {e}")
        return []
    finally:
        conn.close()


def query_litellm_stats(days: int = 30) -> dict:
    """Query usage statistics from REAL LiteLLM DB."""
    conn = _get_litellm_db_connection()
    if not conn:
        return {}

    try:
        with conn.cursor() as cur:
            start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
            month_start = datetime.now(UTC).replace(day=1).strftime("%Y-%m-%d")

            cur.execute(
                """
                SELECT
                    COUNT(*) as requests,
                    SUM(response_cost) as total_cost,
                    SUM(total_tokens) as total_tokens
                FROM spend_logs
                WHERE start_time >= %s
            """,
                (start_date,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) as requests,
                    SUM(response_cost) as total_cost,
                    SUM(total_tokens) as total_tokens
                FROM spend_logs
                WHERE start_time >= %s
            """,
                (month_start,),
            )
            mtd = cur.fetchone()

            return {
                "period_days": days,
                "requests": row["requests"] or 0,
                "total_cost_usd": round(float(row["total_cost"] or 0), 4),
                "total_tokens": row["total_tokens"] or 0,
                "month_to_date": {
                    "requests": mtd["requests"] or 0,
                    "total_cost_usd": round(float(mtd["total_cost"] or 0), 4),
                    "total_tokens": mtd["total_tokens"] or 0,
                },
            }
    except Exception as e:
        logger.error(f"Failed to query stats: {e}")
        return {}
    finally:
        conn.close()


def generate_litellm_summary(days: int = 30) -> dict:
    """Generate LiteLLM usage summary."""
    status = get_litellm_status()
    mtd = get_litellm_month_to_date()

    days_in_month = datetime.now(UTC).day
    projected_monthly = (
        mtd.get("total_cost_usd", 0) / days_in_month * 30 if days_in_month > 0 else 0
    )

    return {
        "type": "litellm_summary",
        "timestamp": datetime.now(UTC).isoformat(),
        "status": status,
        "month_to_date": mtd,
        "trends": {
            "avg_daily_cost_usd": round(mtd.get("total_cost_usd", 0) / 30, 4),
            "projected_monthly_usd": round(projected_monthly, 2),
        },
    }


def ingest_litellm_usage(record: dict) -> bool:
    return True


def get_litellm_daily_data(days: int = 30) -> list[dict]:
    """Placeholder for daily spend data."""
    return []


# 手動錄入的額度資訊 (少爺提供的最新數據)
MANUAL_QUOTAS = {
    "minimax": {"total": 25.0, "remaining": 24.24},
    "kimi": {"total": 25.0, "remaining": 23.67811},
    "glm": {"total": 10.0, "remaining": 10.0},
    "deepseek": {"total": 12.0, "remaining": 10.25},
    "qwen": {"total": 0.0, "remaining": 0.0},  # 免費額度，無儲值
    "xai": {"total": 25.0, "remaining": 25.0},  # Grok-3
}


def get_litellm_manual_summary():
    """回傳手動錄入的額度總計。"""
    total_budget = sum(q["total"] for q in MANUAL_QUOTAS.values())
    total_remaining = sum(q["remaining"] for q in MANUAL_QUOTAS.values())
    total_spent = total_budget - total_remaining

    breakdown = []
    for name, q in MANUAL_QUOTAS.items():
        breakdown.append(
            {
                "name": name,
                "total": q["total"],
                "remaining": q["remaining"],
                "spent": round(q["total"] - q["remaining"], 4),
                "pct": round((q["total"] - q["remaining"]) / q["total"] * 100, 1)
                if q["total"] > 0
                else 0,
            }
        )

    return {
        "total_budget_usd": total_budget,
        "total_remaining_usd": total_remaining,
        "total_spent_usd": round(total_spent, 4),
        "breakdown": breakdown,
    }
