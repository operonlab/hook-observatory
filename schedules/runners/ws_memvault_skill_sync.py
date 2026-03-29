#!/usr/bin/env python3
"""
ws_memvault_skill_sync.py — Daily 5:30AM Anvil → KAS Skill sync

Fetches skill stats from Anvil station, computes proficiency levels,
and upserts SkillProfile records via Core API.

Data flow:
  1. GET Anvil /api/anvil/stats       → per-skill L1 stats
  2. GET Anvil /api/anvil/stats/demand → user vs auto rates
  3. Compute proficiency_level
  4. PUT /api/memvault/kg/skill-profiles/{name} → upsert

Logs: ~/workshop/outputs/memvault/logs/skill_sync.log
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "skill_sync.log"
ANVIL_API = "http://127.0.0.1:10301/api/anvil"
CORE_API = "http://localhost:10000/api/memvault"
SPACE_ID = "default"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[skill_sync] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def http_get(url: str, timeout: int = 10) -> tuple[int | None, dict | list | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        log(f"GET {url} failed: {e}")
        return None, None


def http_put(url: str, body: dict, timeout: int = 10) -> tuple[int | None, dict | None]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:200]
        log(f"PUT {url} HTTP {e.code}: {body_txt}")
        return e.code, None
    except Exception as e:
        log(f"PUT {url} failed: {e}")
        return None, None


def compute_proficiency(total_uses: int, success_rate: float) -> str:
    """Determine proficiency level from usage stats."""
    if total_uses >= 20 and success_rate >= 0.8:
        return "expert"
    if total_uses >= 5 and success_rate >= 0.7:
        return "proficient"
    return "novice"


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Anvil → KAS Skill sync started ==========")

    # Step 1: Fetch per-skill stats from Anvil
    status, stats = http_get(f"{ANVIL_API}/stats")
    if status != 200 or not stats:
        log(f"Failed to fetch Anvil stats: status={status}")
        sys.exit(1)

    if isinstance(stats, dict):
        skills = stats.get("skills", stats.get("items", []))
    elif isinstance(stats, list):
        skills = stats
    else:
        log(f"Unexpected stats format: {type(stats)}")
        sys.exit(1)

    log(f"Fetched {len(skills)} skill stats from Anvil")

    # Step 2: Fetch demand stats (user vs auto rates)
    demand_map: dict[str, dict] = {}
    status, demand = http_get(f"{ANVIL_API}/stats/demand")
    if status == 200 and demand:
        demand_items = demand if isinstance(demand, list) else demand.get("items", [])
        for item in demand_items:
            name = item.get("skill_name") or item.get("name", "")
            if name:
                demand_map[name] = item
        log(f"Fetched demand stats for {len(demand_map)} skills")
    else:
        log(f"Demand stats unavailable (status={status}), skipping auto_rate")

    # Step 3+4: Compute proficiency and upsert
    synced = 0
    errors = 0

    for skill in skills:
        name = skill.get("skill_name") or skill.get("name", "")
        if not name:
            continue

        total_uses = skill.get("total_uses", skill.get("invocation_count", 0)) or 0
        success_rate = skill.get("success_rate", 0.0) or 0.0
        recent_uses = skill.get("recent_uses", skill.get("recent_count", 0)) or 0
        avg_duration_ms = skill.get("avg_duration_ms") or skill.get("avg_duration")

        # Demand data
        demand_data = demand_map.get(name, {})
        auto_count = demand_data.get("auto_count", 0) or 0
        user_count = demand_data.get("user_count", 0) or 0
        auto_rate = None
        if total_uses > 0:
            auto_rate = round(auto_count / max(auto_count + user_count, 1), 4)

        proficiency_level = compute_proficiency(total_uses, success_rate)

        # Build upsert payload
        payload = {
            "skill_name": name,
            "total_uses": total_uses,
            "recent_uses": recent_uses,
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": avg_duration_ms,
            "auto_rate": auto_rate,
            "proficiency_level": proficiency_level,
        }

        url = f"{CORE_API}/kg/skill-profiles/{name}?space_id={SPACE_ID}"
        status, _resp = http_put(url, payload)

        if status in (200, 201):
            synced += 1
        else:
            errors += 1
            log(f"  FAIL: {name} HTTP {status}")

    log(f"Synced: {synced}, Errors: {errors}")
    log("========== Anvil → KAS Skill sync complete ==========")

    if errors > 0 and synced == 0:
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
