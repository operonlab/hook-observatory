import json
import subprocess
import time
import redis
from datetime import UTC, datetime, timedelta
from agent_metrics.config import settings

# Redis 快取設定
r_cache = redis.from_url(settings.REDIS_URL, decode_responses=True)
CACHE_KEY_MTD = "agent-metrics:usage:mtd"
CACHE_KEY_MODELS = "agent-metrics:usage:models"
CACHE_TTL = 600

def _get_ccusage_raw(since: str) -> dict:
    try:
        res = subprocess.run([settings.CCUSAGE_BIN, "daily", "--since", since, "--json"], 
                           capture_output=True, text=True, timeout=45)
        if res.returncode == 0:
            return json.loads(res.stdout)
    except Exception:
        pass
    return {}

def get_month_to_date() -> dict:
    cached = r_cache.get(CACHE_KEY_MTD)
    if cached: return json.loads(cached)

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
            "breakdown": lt_summary["breakdown"]
        }
    }
    r_cache.setex(CACHE_KEY_MTD, CACHE_TTL, json.dumps(data))
    return data

def get_model_breakdown(days: int = 30) -> dict:
    cache_key = f"{CACHE_KEY_MODELS}:{days}"
    cached = r_cache.get(cache_key)
    if cached: return json.loads(cached)

    from agent_metrics import litellm_collector
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
    cc_models = {}
    
    raw = _get_ccusage_raw(since)
    for day in raw.get("daily", []):
        for mb in day.get("modelBreakdowns", []):
            name = mb.get("modelName", "unknown")
            if name not in cc_models: cc_models[name] = {"model": name, "cost_usd": 0.0}
            cc_models[name]["cost_usd"] += mb.get("cost", 0)

    lt_summary = litellm_collector.get_litellm_manual_summary()
    data = {
        "claude_models": sorted(cc_models.values(), key=lambda x: x["cost_usd"], reverse=True),
        "litellm_models": sorted(lt_summary["breakdown"], key=lambda x: x["spent"], reverse=True)
    }
    r_cache.setex(cache_key, CACHE_TTL, json.dumps(data))
    return data

def collect_subscriptions(): return {"providers": []}
def get_daily_data(days=30): return []