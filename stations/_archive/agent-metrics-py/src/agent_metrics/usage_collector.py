import json
import subprocess
import redis
from datetime import UTC, datetime, timedelta
from agent_metrics.config import settings

# Redis 快取設定
r_cache = redis.from_url(settings.REDIS_URL, decode_responses=True)
CACHE_KEY_MTD = "agent-metrics:usage:mtd"
CACHE_KEY_MODELS = "agent-metrics:usage:models"
CACHE_KEY_RAW = "agent-metrics:usage:raw"
CACHE_KEY_DAILY = "agent-metrics:usage:daily-cost"
CACHE_TTL = 600


def _normalize_rs_json(data: dict) -> dict:
    """Convert ccusage-rs JSON format to legacy ccusage format."""
    days = data.get("Daily", [])
    daily = []
    total_cost = 0.0
    total_tokens = 0
    for d in days:
        tc = d.get("total_cost", 0)
        tokens = d.get("total_tokens", {})
        total = sum(
            tokens.get(k, 0)
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_creation_5m_tokens",
                "cache_creation_1h_tokens",
                "cache_read_tokens",
                "thinking_tokens",
            )
        )
        breakdowns = []
        for model_name, mu in d.get("by_model", {}).items():
            cost_obj = mu.get("cost", {})
            breakdowns.append({"modelName": model_name, "cost": sum(cost_obj.values())})
        daily.append(
            {
                "date": d.get("date"),
                "totalCost": tc,
                "modelBreakdowns": breakdowns,
            }
        )
        total_cost += tc
        total_tokens += total
    return {
        "daily": daily,
        "totals": {"totalCost": total_cost, "totalTokens": total_tokens},
    }


def _get_ccusage_raw(since: str) -> dict:
    cache_key = f"{CACHE_KEY_RAW}:{since}"
    cached = r_cache.get(cache_key)
    if cached:
        return json.loads(cached)
    try:
        res = subprocess.run(
            [settings.CCUSAGE_BIN, "daily", "--since", since, "--json"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            if "Daily" in data:
                data = _normalize_rs_json(data)
            r_cache.setex(cache_key, CACHE_TTL, json.dumps(data))
            return data
    except Exception:
        pass
    return {}


def get_month_to_date() -> dict:
    cached = r_cache.get(CACHE_KEY_MTD)
    if cached:
        return json.loads(cached)

    from agent_metrics import litellm_collector

    month_start = datetime.now(UTC).replace(day=1)
    since = month_start.strftime("%Y%m%d")

    cc_raw = _get_ccusage_raw(since).get("totals", {})
    cc_cost = float(cc_raw.get("totalCost", 0))
    lt_summary = litellm_collector.get_litellm_manual_summary()

    data = {
        "claude": {"used_usd": round(cc_cost, 2), "budget_usd": 5000.0},
        "litellm": {
            "used_usd": lt_summary["total_spent_usd"],
            "budget_usd": lt_summary["total_budget_usd"],
            "remaining_usd": lt_summary["total_remaining_usd"],
            "breakdown": lt_summary["breakdown"],
        },
    }
    r_cache.setex(CACHE_KEY_MTD, CACHE_TTL, json.dumps(data))
    return data


def get_model_breakdown(days: int = 30) -> dict:
    cache_key = f"{CACHE_KEY_MODELS}:{days}"
    cached = r_cache.get(cache_key)
    if cached:
        return json.loads(cached)

    from agent_metrics import litellm_collector

    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
    cc_models = {}

    raw = _get_ccusage_raw(since)
    for day in raw.get("daily", []):
        for mb in day.get("modelBreakdowns", []):
            name = mb.get("modelName", "unknown")
            if name not in cc_models:
                cc_models[name] = {"model": name, "cost_usd": 0.0}
            cc_models[name]["cost_usd"] += mb.get("cost", 0)

    lt_summary = litellm_collector.get_litellm_manual_summary()
    data = {
        "claude_models": sorted(cc_models.values(), key=lambda x: x["cost_usd"], reverse=True),
        "litellm_models": sorted(lt_summary["breakdown"], key=lambda x: x["spent"], reverse=True),
    }
    r_cache.setex(cache_key, CACHE_TTL, json.dumps(data))
    return data


def get_today_cost() -> dict:
    """Extract today's cost from ccusage MTD data (shares raw cache)."""
    cached = r_cache.get(CACHE_KEY_DAILY)
    if cached:
        return json.loads(cached)

    today_dash = datetime.now(UTC).strftime("%Y-%m-%d")
    month_start = datetime.now(UTC).replace(day=1).strftime("%Y%m%d")

    raw = _get_ccusage_raw(month_start)
    cost = 0.0
    for day in raw.get("daily", []):
        if day.get("date") == today_dash:
            cost = float(day.get("totalCost", 0))
            break

    data = {
        "date": today_dash,
        "cost": round(cost, 2),
        "updated": datetime.now(UTC).isoformat(),
    }
    r_cache.setex(CACHE_KEY_DAILY, CACHE_TTL, json.dumps(data))
    return data


def write_daily_json(path: str | None = None) -> None:
    """Write today's cost to JSON file for statusline.sh consumption."""
    import os
    import tempfile

    target = path or os.path.expanduser("~/.claude/data/llm-usage/daily.json")
    data = get_today_cost()
    dir_path = os.path.dirname(target)
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.rename(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def collect_subscriptions():
    return {"providers": []}


def get_daily_data(days=30):
    return []
