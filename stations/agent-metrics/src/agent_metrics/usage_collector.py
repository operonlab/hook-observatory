"""Usage Collector — subscription tracking + ccusage CLI data.

Merged from llm-usage station's subscription_collector.py + ccusage_adapter.py.

Collects:
- Claude Code: sysmon API (5h/7d window percentages)
- Codex CLI / Gemini CLI: installation + basic status
- LiteLLM: proxy health + model availability from /health API
- ccusage: daily cost data, model breakdowns, month-to-date
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_metrics.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _parse_pct(val: str | int | float) -> int | None:
    if isinstance(val, str) and val.endswith("%"):
        try:
            return int(val.rstrip("%"))
        except ValueError:
            pass
    if isinstance(val, (int, float)):
        return int(val)
    return None


def _fetch_sysmon_usage() -> tuple[int | None, int | None]:
    """Fetch CC usage from in-process quota collector cache."""
    try:
        from agent_metrics.quota_collector import get_quota_sync

        quota = get_quota_sync()
        if not quota:
            return None, None
        cc_5h = _parse_pct(quota.get("llm_cc_5h", "?"))
        cc_7d = _parse_pct(quota.get("llm_cc_7d", "?"))
        return cc_5h, cc_7d
    except Exception:
        return None, None


def _count_cc_sessions_today() -> int | None:
    """Count Claude Code sessions from today by checking project dirs."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["find", str(projects_dir), "-maxdepth", "2", "-name", "*.jsonl", "-mtime", "-1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    return len(out.splitlines()) if out else 0


# ---------------------------------------------------------------------------
# Subscription collection
# ---------------------------------------------------------------------------


def _collect_claude_code() -> dict:
    """Collect Claude Code subscription usage via sysmon API."""
    sub_cfg = settings.SUBSCRIPTIONS.get("claude-code", {})
    result = {
        "provider": "anthropic",
        "cli": "claude-code",
        "plan": sub_cfg.get("plan", "max_5"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 100.00),
        "collected_at": datetime.now(UTC).isoformat(),
    }

    cc_5h, cc_7d = _fetch_sysmon_usage()
    if cc_5h is not None:
        result["quota_5h_pct"] = cc_5h
        result["quota_7d_pct"] = cc_7d
        result["source"] = "sysmon_api"
    else:
        state_path = Path(settings.MODEL_POLICY_STATE_PATH).expanduser()
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            result["current_mode"] = state.get("mode", "unknown")
            result["mode_updated_at"] = state.get("updated_at")
            result["source"] = "state_file"
        else:
            result["source"] = "unavailable"

    session_count = _count_cc_sessions_today()
    if session_count is not None:
        result["sessions_today"] = session_count

    return result


def _collect_codex() -> dict:
    """Collect Codex CLI subscription usage (best-effort)."""
    sub_cfg = settings.SUBSCRIPTIONS.get("codex-cli", {})
    result = {
        "provider": "openai",
        "cli": "codex-cli",
        "plan": sub_cfg.get("plan", "pro"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 200.00),
        "collected_at": datetime.now(UTC).isoformat(),
    }
    codex_path = _run("which codex 2>/dev/null")
    result["installed"] = bool(codex_path)
    if not codex_path:
        result["source"] = "not_installed"
        return result
    usage_out = _run("codex usage 2>/dev/null")
    if usage_out:
        result["raw_usage"] = usage_out
        result["source"] = "cli_usage"
    else:
        result["source"] = "no_usage_api"
    return result


def _collect_gemini() -> dict:
    """Collect Gemini CLI subscription usage (best-effort)."""
    sub_cfg = settings.SUBSCRIPTIONS.get("gemini-cli", {})
    result = {
        "provider": "google",
        "cli": "gemini-cli",
        "plan": sub_cfg.get("plan", "advanced"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 0),
        "collected_at": datetime.now(UTC).isoformat(),
    }
    gemini_path = _run("which gemini 2>/dev/null")
    result["installed"] = bool(gemini_path)
    if not gemini_path:
        result["source"] = "not_installed"
        return result
    result["source"] = "installed_no_usage_api"
    return result


def _collect_litellm() -> dict:
    """Collect LiteLLM proxy status and model health."""
    sub_cfg = settings.SUBSCRIPTIONS.get("litellm", {})
    result = {
        "provider": "multi",
        "cli": "litellm",
        "plan": sub_cfg.get("plan", "self-hosted"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 0),
        "collected_at": datetime.now(UTC).isoformat(),
    }

    # Check if proxy is alive (no auth required)
    try:
        req = urllib.request.Request(
            f"{settings.LITELLM_BASE_URL}/health/liveliness",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            result["proxy_alive"] = resp.status == 200
    except Exception:
        result["proxy_alive"] = False
        result["source"] = "unreachable"
        return result

    # Fetch model health (requires auth)
    try:
        req = urllib.request.Request(
            f"{settings.LITELLM_BASE_URL}/health",
            headers={
                "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        healthy = data.get("healthy_endpoints", [])
        unhealthy = data.get("unhealthy_endpoints", [])

        result["models_healthy"] = len(healthy)
        result["models_unhealthy"] = len(unhealthy)
        result["models_total"] = len(healthy) + len(unhealthy)
        result["healthy_models"] = [ep.get("model", "?") for ep in healthy]
        result["unhealthy_models"] = [
            {
                "model": ep.get("model", "?"),
                "error": str(ep.get("error", ""))[:100],
            }
            for ep in unhealthy
        ]
        result["source"] = "health_api"
    except Exception as e:
        result["source"] = "health_api_error"
        result["error"] = str(e)[:100]

    return result


def collect_subscriptions() -> dict:
    """Collect subscription usage for all providers."""
    result = {
        "type": "subscription_usage",
        "timestamp": datetime.now(UTC).isoformat(),
        "providers": [],
    }
    for fn in (_collect_claude_code, _collect_codex, _collect_gemini, _collect_litellm):
        result["providers"].append(fn())
    result["total_monthly_cost_usd"] = sum(
        p.get("monthly_cost_usd", 0) for p in result["providers"]
    )
    return result


# ---------------------------------------------------------------------------
# ccusage CLI data
# ---------------------------------------------------------------------------


def _fetch_ccusage_daily(days: int = 30) -> dict:
    """Call ccusage daily --since YYYYMMDD --json and return parsed result."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
    try:
        r = subprocess.run(
            [settings.CCUSAGE_BIN, "daily", "--since", since, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ccusage error: {e}", file=sys.stderr)
    return {"daily": [], "totals": {}}


def get_daily_data(days: int = 30) -> list[dict]:
    """Get normalized daily data from ccusage."""
    raw = _fetch_ccusage_daily(days)
    result = []
    for day in raw.get("daily", []):
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

    month_prefix = datetime.now(UTC).strftime("%Y-%m")
    monthly = [d for d in daily if d["date"].startswith(month_prefix)]

    total_cost = sum(d["cost_usd"] for d in monthly)
    total_in = sum(d["tokens_in"] for d in monthly)
    total_out = sum(d["tokens_out"] for d in monthly)
    total_cache_creation = sum(d["cache_creation"] for d in monthly)
    total_cache_read = sum(d["cache_read"] for d in monthly)

    total_input = total_in + total_cache_creation + total_cache_read
    cache_hit_rate = round(total_cache_read / total_input * 100, 1) if total_input > 0 else 0
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
            m["requests"] += 1
            m["tokens_in"] += mb.get("inputTokens", 0)
            m["tokens_out"] += mb.get("outputTokens", 0)
            m["cache_creation"] += mb.get("cacheCreationTokens", 0)
            m["cache_read"] += mb.get("cacheReadTokens", 0)
            m["cost_usd"] += mb.get("cost", 0)

    for m in models.values():
        m["cost_usd"] = round(m["cost_usd"], 4)
        total_input = m["tokens_in"] + m["cache_creation"] + m["cache_read"]
        m["cache_hit_rate"] = (
            round(m["cache_read"] / total_input * 100, 1) if total_input > 0 else 0
        )

    return sorted(models.values(), key=lambda x: x["cost_usd"], reverse=True)
