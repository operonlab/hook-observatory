#!/usr/bin/env python3
"""
API Usage Collector — tracks pay-per-use LLM API costs via LiteLLM.

Collects usage data from LiteLLM Proxy's spend tracking API:
- Per-model token counts and costs
- Cache hit rates
- Request counts

Usage:
    python3 api_collector.py                    # Collect current month
    python3 api_collector.py --days 7           # Last 7 days
    python3 api_collector.py --output FILE      # Write to file
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# LiteLLM Spend API
# ---------------------------------------------------------------------------


def _litellm_request(
    base_url: str,
    endpoint: str,
    master_key: str,
    params: dict | None = None,
) -> dict | list | None:
    """Make authenticated request to LiteLLM API."""
    url = f"{base_url}{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url = f"{url}?{qs}"

    headers = {
        "Authorization": f"Bearer {master_key}",
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"LiteLLM API error ({endpoint}): {e}", file=sys.stderr)
        return None


def collect_spend_by_model(
    base_url: str,
    master_key: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Get spend breakdown by model from LiteLLM."""
    # /spend/tags or /spend/logs endpoint
    data = _litellm_request(
        base_url,
        "/spend/logs",
        master_key,
        params={"start_date": start_date, "end_date": end_date},
    )

    if not data or not isinstance(data, list):
        return []

    # Aggregate by model
    model_stats: dict[str, dict] = {}
    for entry in data:
        model = entry.get("model", "unknown")
        if model not in model_stats:
            model_stats[model] = {
                "model": model,
                "provider": _infer_provider(model),
                "requests": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
            }

        s = model_stats[model]
        s["requests"] += 1
        s["tokens_in"] += entry.get("prompt_tokens", 0) or 0
        s["tokens_out"] += entry.get("completion_tokens", 0) or 0
        s["cached_tokens"] += entry.get("cache_read_input_tokens", 0) or 0
        s["cost_usd"] += entry.get("spend", 0) or 0

    # Calculate cache hit rates
    for s in model_stats.values():
        total_in = s["tokens_in"] + s["cached_tokens"]
        s["cache_hit_rate"] = (
            round(s["cached_tokens"] / total_in * 100, 1) if total_in > 0 else 0
        )
        s["cost_usd"] = round(s["cost_usd"], 4)

    return sorted(model_stats.values(), key=lambda x: x["cost_usd"], reverse=True)


def collect_spend_daily(
    base_url: str,
    master_key: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Get daily spend totals from LiteLLM."""
    data = _litellm_request(
        base_url,
        "/spend/logs",
        master_key,
        params={"start_date": start_date, "end_date": end_date},
    )

    if not data or not isinstance(data, list):
        return []

    # Aggregate by day
    daily: dict[str, dict] = {}
    for entry in data:
        ts = entry.get("startTime", "") or entry.get("start_time", "")
        if not ts:
            continue
        day = ts[:10]  # YYYY-MM-DD
        if day not in daily:
            daily[day] = {
                "date": day,
                "requests": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
            }

        d = daily[day]
        d["requests"] += 1
        d["tokens_in"] += entry.get("prompt_tokens", 0) or 0
        d["tokens_out"] += entry.get("completion_tokens", 0) or 0
        d["cost_usd"] += entry.get("spend", 0) or 0

    for d in daily.values():
        d["cost_usd"] = round(d["cost_usd"], 4)

    return sorted(daily.values(), key=lambda x: x["date"])


def _infer_provider(model: str) -> str:
    """Infer provider from model name."""
    model_lower = model.lower()
    if any(k in model_lower for k in ("claude", "haiku", "sonnet", "opus")):
        return "anthropic"
    if any(k in model_lower for k in ("gpt", "o1", "o3", "o4")):
        return "openai"
    if any(k in model_lower for k in ("gemini", "gemma")):
        return "google"
    if "deepseek" in model_lower:
        return "deepseek"
    if any(k in model_lower for k in ("qwen", "dashscope")):
        return "alibaba"
    if any(k in model_lower for k in ("glm", "z.ai")):
        return "zhipu"
    if any(k in model_lower for k in ("kimi", "moonshot")):
        return "moonshot"
    if "minimax" in model_lower:
        return "minimax"
    return "unknown"


# ---------------------------------------------------------------------------
# Main collection
# ---------------------------------------------------------------------------


def collect_api_usage(config: dict, days: int = 30) -> dict:
    """Collect API usage from LiteLLM for the specified period."""
    api_cfg = config.get("api", {}).get("litellm", {})
    base_url = api_cfg.get("base_url", "http://localhost:4000")
    master_key_env = api_cfg.get("master_key_env", "LITELLM_MASTER_KEY")
    master_key = os.environ.get(master_key_env, "")

    budget_cfg = config.get("api", {})
    monthly_budget = budget_cfg.get("monthly_budget_usd", 50.00)

    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Month start for budget tracking
    month_start = datetime.now(UTC).replace(day=1).strftime("%Y-%m-%d")

    result = {
        "type": "api_usage",
        "timestamp": datetime.now(UTC).isoformat(),
        "period": {"start": start_date, "end": end_date, "days": days},
        "litellm_available": False,
    }

    if not master_key:
        result["error"] = (
            f"Missing {master_key_env} environment variable. "
            "Set it to your LiteLLM master key."
        )
        return result

    # Test connectivity
    health = _litellm_request(base_url, "/health", master_key)
    if health is None:
        result["error"] = f"Cannot reach LiteLLM at {base_url}"
        return result

    result["litellm_available"] = True

    # Collect by-model breakdown
    by_model = collect_spend_by_model(base_url, master_key, start_date, end_date)
    result["by_model"] = by_model

    # Collect daily trends
    daily = collect_spend_daily(base_url, master_key, start_date, end_date)
    result["daily"] = daily

    # Month-to-date totals for budget tracking
    mtd_models = collect_spend_by_model(
        base_url, master_key, month_start, end_date,
    )
    mtd_total = sum(m.get("cost_usd", 0) for m in mtd_models)
    mtd_tokens_in = sum(m.get("tokens_in", 0) for m in mtd_models)
    mtd_tokens_out = sum(m.get("tokens_out", 0) for m in mtd_models)
    mtd_cached = sum(m.get("cached_tokens", 0) for m in mtd_models)
    mtd_requests = sum(m.get("requests", 0) for m in mtd_models)

    total_input = mtd_tokens_in + mtd_cached
    cache_savings = _estimate_cache_savings(mtd_cached, mtd_models)

    result["month_to_date"] = {
        "period": {"start": month_start, "end": end_date},
        "total_cost_usd": round(mtd_total, 4),
        "budget_usd": monthly_budget,
        "budget_used_pct": (
            round(mtd_total / monthly_budget * 100, 1)
            if monthly_budget > 0
            else 0
        ),
        "total_requests": mtd_requests,
        "total_tokens_in": mtd_tokens_in,
        "total_tokens_out": mtd_tokens_out,
        "total_cached_tokens": mtd_cached,
        "cache_hit_rate": (
            round(mtd_cached / total_input * 100, 1) if total_input > 0 else 0
        ),
        "estimated_cache_savings_usd": round(cache_savings, 4),
    }

    return result


def _estimate_cache_savings(cached_tokens: int, models: list[dict]) -> float:
    """Estimate how much money was saved by caching.

    Cached tokens are typically billed at 10% of input price.
    Savings ≈ cached_tokens * (input_price - cache_price).
    Uses a rough average of $3/MTok input for estimation.
    """
    # Rough input price: $3/MTok average across models
    input_price_per_tok = 3.0 / 1_000_000
    cache_price_per_tok = input_price_per_tok * 0.1
    savings = cached_tokens * (input_price_per_tok - cache_price_per_tok)
    return savings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="API Usage Collector (LiteLLM)",
    )
    parser.add_argument(
        "--days", "-d", type=int, default=30,
        help="Number of days to collect (default: 30)",
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

    result = collect_api_usage(config, days=args.days)

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
