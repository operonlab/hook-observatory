#!/usr/bin/env python3
"""
LLM Usage Station API — FastAPI microservice.

Endpoints:
    GET /summary       — Dual-track merged summary
    GET /trends        — Daily trends + 7d moving avg + projection
    GET /by-model      — Per-model + provider breakdown
    GET /budget        — Monthly budget tracking
    GET /cache         — Cache efficiency stats
    GET /subscription  — Per-CLI subscription status
    GET /health        — Health check

Port: 9525 (configurable via config.json)

Usage:
    python3 api.py
    python3 api.py --port 9525
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import uvicorn
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from starlette.requests import Request
except ImportError:
    print(
        "ERROR: fastapi and uvicorn are required.\n"
        "  uv pip install fastapi uvicorn",
        file=sys.stderr,
    )
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from analyzer import generate_by_model, generate_summary, generate_trends
from api_collector import load_config
from collector import UnifiedCollector

DEFAULT_CONFIG = SCRIPT_DIR / "config.json"

app = FastAPI(
    title="LLM Usage API",
    description="Dual-track LLM usage tracking — subscription + API",
    version="2.0.0",
)

app.mount("/static", StaticFiles(directory=SCRIPT_DIR / "static"), name="static")
templates = Jinja2Templates(directory=SCRIPT_DIR / "templates")

_config: dict = {}
_collector: UnifiedCollector | None = None


def _get_config() -> dict:
    global _config
    if not _config:
        _config = load_config(DEFAULT_CONFIG)
    return _config


def _get_collector() -> UnifiedCollector:
    global _collector
    if not _collector:
        _collector = UnifiedCollector(_get_config())
    return _collector


def _read_latest() -> dict | None:
    """Read latest.json from disk."""
    return _get_collector().read_latest()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the dashboard UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/summary")
def summary_endpoint():
    """Dual-track merged summary: subscription + API month-to-date."""
    config = _get_config()
    return generate_summary(config)


@app.get("/trends")
def trends_endpoint(days: int = Query(default=30, ge=1, le=365)):
    """Daily trends with 7-day moving average and monthly projection."""
    config = _get_config()
    return generate_trends(config, days=days)


@app.get("/by-model")
def by_model_endpoint(days: int = Query(default=30, ge=1, le=365)):
    """Per-model and per-provider cost breakdown."""
    config = _get_config()
    return generate_by_model(config, days=days)


@app.get("/budget")
def budget_endpoint():
    """Monthly budget tracking for API spend."""
    config = _get_config()
    latest = _read_latest()

    api_cfg = config.get("api", {})
    budget_usd = api_cfg.get("monthly_budget_usd", 50.0)
    warning_pct = api_cfg.get("budget_warning_pct", 80)

    # Prefer latest snapshot; fall back to live query
    if latest and "api" in latest:
        mtd = latest["api"].get("month_to_date", {})
    else:
        from api_collector import collect_api_usage
        api_data = collect_api_usage(config, days=30)
        mtd = api_data.get("month_to_date", {})

    used_usd = mtd.get("total_cost_usd", 0)
    remaining = round(budget_usd - used_usd, 4)
    pct = round(used_usd / budget_usd * 100, 1) if budget_usd > 0 else 0

    return {
        "type": "budget",
        "timestamp": datetime.now(UTC).isoformat(),
        "budget_usd": budget_usd,
        "used_usd": used_usd,
        "remaining_usd": remaining,
        "used_pct": pct,
        "warning_threshold_pct": warning_pct,
        "over_warning": pct >= warning_pct,
        "over_budget": used_usd >= budget_usd,
    }


@app.get("/cache")
def cache_endpoint():
    """Cache efficiency statistics."""
    config = _get_config()
    latest = _read_latest()

    if latest and "api" in latest:
        mtd = latest["api"].get("month_to_date", {})
    else:
        from api_collector import collect_api_usage
        api_data = collect_api_usage(config, days=30)
        mtd = api_data.get("month_to_date", {})

    return {
        "type": "cache_stats",
        "timestamp": datetime.now(UTC).isoformat(),
        "cache_hit_rate_pct": mtd.get("cache_hit_rate", 0),
        "cached_tokens": mtd.get("total_cached_tokens", 0),
        "total_input_tokens": mtd.get("total_tokens_in", 0),
        "estimated_savings_usd": mtd.get("estimated_cache_savings_usd", 0),
    }


@app.get("/subscription")
def subscription_endpoint():
    """Per-CLI subscription status and quota usage."""
    config = _get_config()
    latest = _read_latest()

    if latest and "subscription" in latest:
        return latest["subscription"]

    from subscription_collector import collect_all
    return collect_all(config)


@app.get("/health")
def health_endpoint():
    """Health check."""
    collector = _get_collector()
    latest = collector.read_latest()
    has_data = latest is not None

    return {
        "status": "ok",
        "station": "llm-usage",
        "version": "2.0.0",
        "has_snapshot": has_data,
        "latest_timestamp": latest.get("timestamp") if latest else None,
        "snapshot_dir": str(collector.snapshot_dir),
        "snapshot_count": len(list(collector.snapshot_dir.glob("*.json")))
        if collector.snapshot_dir.exists()
        else 0,
    }


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="LLM Usage API Server")
    parser.add_argument("--port", type=int, help="Port (default: from config)")
    parser.add_argument("--host", type=str, help="Host (default: from config)")
    parser.add_argument("--config", type=str, help="Config file path")
    args = parser.parse_args()

    global _config
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    _config = load_config(config_path)

    server_cfg = _config.get("server", {})
    host = args.host or server_cfg.get("host", "127.0.0.1")
    port = args.port or server_cfg.get("port", 9525)

    print(f"Starting LLM Usage API on {host}:{port}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
