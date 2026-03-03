"""Usage Analyzer — summary, trends, and by-model breakdown.

Ported from llm-usage station's analyzer.py.
Combines subscription (fixed monthly) + ccusage (actual spend) into unified views.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_metrics.usage_collector import (
    collect_subscriptions,
    get_daily_data,
    get_model_breakdown,
    get_month_to_date,
)


def generate_summary() -> dict:
    """Generate current month dual-track summary."""
    sub_data = collect_subscriptions()
    mtd = get_month_to_date()

    sub_total = sub_data.get("total_monthly_cost_usd", 0)
    providers = sub_data.get("providers", [])
    api_total = mtd.get("total_cost_usd", 0)
    combined_total = round(sub_total + api_total, 2)

    return {
        "type": "summary",
        "timestamp": datetime.now(UTC).isoformat(),
        "period": datetime.now(UTC).strftime("%Y-%m"),
        "subscription": {
            "total_monthly_usd": sub_total,
            "providers": [
                {
                    "cli": p.get("cli"),
                    "provider": p.get("provider"),
                    "plan": p.get("plan"),
                    "cost_usd": p.get("monthly_cost_usd", 0),
                    "quota_5h_pct": p.get("quota_5h_pct"),
                    "quota_7d_pct": p.get("quota_7d_pct"),
                    "current_mode": p.get("current_mode"),
                    "source": p.get("source"),
                }
                for p in providers
            ],
        },
        "api": {
            "month_to_date_usd": api_total,
            "total_tokens_in": mtd.get("total_tokens_in", 0),
            "total_tokens_out": mtd.get("total_tokens_out", 0),
            "cache_hit_rate": mtd.get("cache_hit_rate", 0),
            "cache_savings_usd": mtd.get("estimated_cache_savings_usd", 0),
        },
        "combined": {
            "total_monthly_usd": combined_total,
            "subscription_usd": sub_total,
            "api_usd": api_total,
            "subscription_pct": (
                round(sub_total / combined_total * 100, 1) if combined_total > 0 else 0
            ),
            "api_pct": (
                round(api_total / combined_total * 100, 1) if combined_total > 0 else 0
            ),
        },
    }


def generate_trends(days: int = 30) -> dict:
    """Generate daily cost trend data from ccusage."""
    daily = get_daily_data(days=days)

    running_total = 0.0
    enriched_daily = []
    for i, day in enumerate(daily):
        cost = day.get("cost_usd", 0)
        running_total += cost
        entry = {
            "date": day["date"],
            "cost_usd": cost,
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
        "type": "trends",
        "timestamp": datetime.now(UTC).isoformat(),
        "period_days": days,
        "daily": enriched_daily,
        "summary": {
            "total_cost_usd": round(running_total, 4),
            "avg_daily_cost_usd": round(avg_daily_cost, 4),
            "projected_monthly_usd": projected_monthly,
        },
    }


def generate_by_model(days: int = 30) -> dict:
    """Generate per-model cost breakdown from ccusage."""
    models = get_model_breakdown(days=days)
    total_cost = sum(m.get("cost_usd", 0) for m in models)

    for m in models:
        m["pct_of_total"] = (
            round(m.get("cost_usd", 0) / total_cost * 100, 1) if total_cost > 0 else 0
        )

    by_provider: dict[str, dict] = {}
    for m in models:
        provider = m.get("provider", "unknown")
        if provider not in by_provider:
            by_provider[provider] = {
                "provider": provider,
                "models": [],
                "total_cost_usd": 0,
                "total_requests": 0,
            }
        by_provider[provider]["models"].append(m)
        by_provider[provider]["total_cost_usd"] += m.get("cost_usd", 0)
        by_provider[provider]["total_requests"] += m.get("requests", 0)

    for p in by_provider.values():
        p["total_cost_usd"] = round(p["total_cost_usd"], 4)

    provider_list = sorted(
        by_provider.values(),
        key=lambda x: x["total_cost_usd"],
        reverse=True,
    )

    return {
        "type": "by_model",
        "timestamp": datetime.now(UTC).isoformat(),
        "period_days": days,
        "total_cost_usd": round(total_cost, 4),
        "model_count": len(models),
        "models": models,
        "by_provider": provider_list,
    }
