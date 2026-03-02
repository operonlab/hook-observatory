#!/usr/bin/env python3
"""
ccusage Adapter — bridges ccusage CLI data into LLM Usage Station.

Replaces LiteLLM API collector with real Claude Code usage data from ccusage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

CCUSAGE_BIN = "/opt/homebrew/bin/ccusage"
DAILY_JSON = Path.home() / ".claude" / "data" / "llm-usage" / "daily.json"


def fetch_ccusage_daily(days: int = 30) -> dict:
    """Call ccusage daily --since YYYYMMDD --json and return parsed result.

    Returns dict with keys: daily (list), totals (dict).
    On failure returns empty structure.
    """
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
    try:
        r = subprocess.run(
            [CCUSAGE_BIN, "daily", "--since", since, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ccusage error: {e}", file=sys.stderr)

    return {"daily": [], "totals": {}}


def read_daily_json() -> dict | None:
    """Read ~/.claude/data/llm-usage/daily.json as today fallback."""
    if DAILY_JSON.exists():
        try:
            with open(DAILY_JSON) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_daily_data(days: int = 30) -> list[dict]:
    """Get normalized daily data from ccusage.

    Returns list of dicts with keys:
        date, cost_usd, tokens_in, tokens_out, cache_creation, cache_read,
        total_tokens, model_breakdowns
    """
    raw = fetch_ccusage_daily(days)
    daily_list = raw.get("daily", [])

    result = []
    for day in daily_list:
        result.append({
            "date": day.get("date", ""),
            "cost_usd": round(day.get("totalCost", 0), 4),
            "tokens_in": day.get("inputTokens", 0),
            "tokens_out": day.get("outputTokens", 0),
            "cache_creation": day.get("cacheCreationTokens", 0),
            "cache_read": day.get("cacheReadTokens", 0),
            "total_tokens": day.get("totalTokens", 0),
            "model_breakdowns": day.get("modelBreakdowns", []),
        })

    return sorted(result, key=lambda x: x["date"])


def get_month_to_date() -> dict:
    """Get current month aggregated data from ccusage."""
    month_start = datetime.now(UTC).replace(day=1)
    days_since = (datetime.now(UTC) - month_start).days + 1

    daily = get_daily_data(days=days_since)

    # Filter to current month only
    month_prefix = datetime.now(UTC).strftime("%Y-%m")
    monthly = [d for d in daily if d["date"].startswith(month_prefix)]

    total_cost = sum(d["cost_usd"] for d in monthly)
    total_in = sum(d["tokens_in"] for d in monthly)
    total_out = sum(d["tokens_out"] for d in monthly)
    total_cache_creation = sum(d["cache_creation"] for d in monthly)
    total_cache_read = sum(d["cache_read"] for d in monthly)

    # Cache hit rate: cache_read / (tokens_in + cache_creation + cache_read)
    total_input = total_in + total_cache_creation + total_cache_read
    cache_hit_rate = (
        round(total_cache_read / total_input * 100, 1) if total_input > 0 else 0
    )

    # Cache savings estimate:
    # cache_read tokens billed at 10% of input price ($15/MTok for Opus)
    # savings = cache_read * (full_price - cache_price)
    # Rough avg: $10/MTok input, cache at $1/MTok → save $9/MTok
    savings = total_cache_read * 9.0 / 1_000_000

    return {
        "total_cost_usd": round(total_cost, 2),
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "total_cache_creation": total_cache_creation,
        "total_cache_read": total_cache_read,
        "cache_hit_rate": cache_hit_rate,
        "estimated_cache_savings_usd": round(savings, 2),
        "days": len(monthly),
    }


def get_model_breakdown(days: int = 30) -> list[dict]:
    """Aggregate model breakdowns across all days."""
    daily = get_daily_data(days=days)

    models: dict[str, dict] = {}
    for day in daily:
        for mb in day.get("model_breakdowns", []):
            name = mb.get("modelName", "unknown")
            if name not in models:
                models[name] = {
                    "model": name,
                    "provider": "anthropic",
                    "requests": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cache_creation": 0,
                    "cache_read": 0,
                    "cost_usd": 0.0,
                }
            m = models[name]
            m["requests"] += 1  # one entry per day = approx
            m["tokens_in"] += mb.get("inputTokens", 0)
            m["tokens_out"] += mb.get("outputTokens", 0)
            m["cache_creation"] += mb.get("cacheCreationTokens", 0)
            m["cache_read"] += mb.get("cacheReadTokens", 0)
            m["cost_usd"] += mb.get("cost", 0)

    # Finalize
    for m in models.values():
        m["cost_usd"] = round(m["cost_usd"], 4)
        total_input = m["tokens_in"] + m["cache_creation"] + m["cache_read"]
        m["cache_hit_rate"] = (
            round(m["cache_read"] / total_input * 100, 1) if total_input > 0 else 0
        )

    return sorted(models.values(), key=lambda x: x["cost_usd"], reverse=True)
