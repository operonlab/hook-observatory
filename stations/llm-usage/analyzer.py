#!/usr/bin/env python3
"""
LLM Usage Analyzer — unified dual-track analysis engine.

Combines subscription (fixed monthly) + API (pay-per-use) data into:
- summary: current month overview
- trends: 7/30 day time series
- by-model: per-model cost breakdown

Usage:
    python3 analyzer.py summary               # Monthly overview
    python3 analyzer.py trends --days 7        # 7-day trend
    python3 analyzer.py by-model               # Per-model breakdown
    python3 analyzer.py --output FILE          # Write to file
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from api_collector import collect_api_usage, load_config
from subscription_collector import collect_all as collect_subscriptions

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def generate_summary(config: dict) -> dict:
    """Generate current month dual-track summary."""
    sub_data = collect_subscriptions(config)
    api_data = collect_api_usage(config, days=30)

    # Subscription totals
    sub_total = sub_data.get("total_monthly_cost_usd", 0)
    providers = sub_data.get("providers", [])

    # API totals
    mtd = api_data.get("month_to_date", {})
    api_total = mtd.get("total_cost_usd", 0)
    api_budget = mtd.get("budget_usd", 0)
    api_budget_pct = mtd.get("budget_used_pct", 0)

    # Combined
    combined_total = round(sub_total + api_total, 2)

    summary = {
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
            "budget_usd": api_budget,
            "budget_used_pct": api_budget_pct,
            "total_requests": mtd.get("total_requests", 0),
            "total_tokens_in": mtd.get("total_tokens_in", 0),
            "total_tokens_out": mtd.get("total_tokens_out", 0),
            "cache_hit_rate": mtd.get("cache_hit_rate", 0),
            "cache_savings_usd": mtd.get(
                "estimated_cache_savings_usd", 0,
            ),
            "available": api_data.get("litellm_available", False),
            "error": api_data.get("error"),
        },
        "combined": {
            "total_monthly_usd": combined_total,
            "subscription_usd": sub_total,
            "api_usd": api_total,
            "subscription_pct": (
                round(sub_total / combined_total * 100, 1)
                if combined_total > 0
                else 0
            ),
            "api_pct": (
                round(api_total / combined_total * 100, 1)
                if combined_total > 0
                else 0
            ),
        },
    }

    return summary


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


def generate_trends(config: dict, days: int = 30) -> dict:
    """Generate daily cost trend data."""
    api_data = collect_api_usage(config, days=days)

    daily = api_data.get("daily", [])

    # Calculate running totals and moving averages
    running_total = 0.0
    enriched_daily = []
    for i, day in enumerate(daily):
        running_total += day.get("cost_usd", 0)
        entry = {
            **day,
            "cumulative_cost_usd": round(running_total, 4),
        }

        # 7-day moving average
        if i >= 6:
            window = daily[i - 6 : i + 1]
            avg = sum(d.get("cost_usd", 0) for d in window) / 7
            entry["cost_7d_avg_usd"] = round(avg, 4)

        enriched_daily.append(entry)

    # Projection for rest of month
    days_elapsed = len(daily) or 1
    avg_daily_cost = running_total / days_elapsed
    days_in_month = 30  # approximation
    projected_monthly = round(avg_daily_cost * days_in_month, 2)

    return {
        "type": "trends",
        "timestamp": datetime.now(UTC).isoformat(),
        "period_days": days,
        "daily": enriched_daily,
        "summary": {
            "total_cost_usd": round(running_total, 4),
            "avg_daily_cost_usd": round(avg_daily_cost, 4),
            "projected_monthly_usd": projected_monthly,
            "total_requests": sum(
                d.get("requests", 0) for d in daily
            ),
            "total_tokens": sum(
                d.get("tokens_in", 0) + d.get("tokens_out", 0) for d in daily
            ),
        },
        "available": api_data.get("litellm_available", False),
        "error": api_data.get("error"),
    }


# ---------------------------------------------------------------------------
# By-model breakdown
# ---------------------------------------------------------------------------


def generate_by_model(config: dict, days: int = 30) -> dict:
    """Generate per-model cost breakdown."""
    api_data = collect_api_usage(config, days=days)

    models = api_data.get("by_model", [])
    total_cost = sum(m.get("cost_usd", 0) for m in models)

    # Add percentage of total
    for m in models:
        m["pct_of_total"] = (
            round(m.get("cost_usd", 0) / total_cost * 100, 1)
            if total_cost > 0
            else 0
        )

    # Group by provider
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
        "available": api_data.get("litellm_available", False),
        "error": api_data.get("error"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="LLM Usage Analyzer",
    )
    parser.add_argument(
        "command",
        choices=["summary", "trends", "by-model"],
        help="Analysis command",
    )
    parser.add_argument(
        "--days", "-d", type=int, default=30,
        help="Period in days (for trends/by-model)",
    )
    parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    parser.add_argument(
        "--compact", action="store_true",
        help="Compact JSON",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = load_config(config_path)

    if args.command == "summary":
        result = generate_summary(config)
    elif args.command == "trends":
        result = generate_trends(config, days=args.days)
    elif args.command == "by-model":
        result = generate_by_model(config, days=args.days)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n")
        print(f"Report saved to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
