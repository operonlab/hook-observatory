#!/usr/bin/env python3
"""
ws_drift_detection.py — Daily DailyOS goal drift detection + notification

Pipeline:
  1. Fetch today's DailyOS plan via SDK
  2. Calculate completion rate from items
  3. If drifting (score < threshold) → push notification

Logs: ~/workshop/outputs/scheduler/logs/ws-drift-detection.log
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-drift-detection.log"
CORE_URL = os.getenv("CORE_URL", "http://127.0.0.1:8801")
INTERNAL_KEY = os.getenv("CORE_INTERNAL_API_KEY", "")
SPACE_ID = os.getenv("WORKSHOP_SPACE_ID", "default")

DRIFT_THRESHOLD = 50  # Alert if completion < 50%

os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[drift-detection] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def api_get(path: str) -> dict | None:
    """GET from Core API with internal key auth."""
    url = f"{CORE_URL}{path}"
    req = urllib.request.Request(url)
    req.add_header("Content-Type", "application/json")
    if INTERNAL_KEY:
        req.add_header("X-Internal-Key", INTERNAL_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"GET {path} failed: {e}")
        return None


def api_post(path: str, data: dict) -> int | None:
    """POST to Core API with internal key auth. Returns status code."""
    url = f"{CORE_URL}{path}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if INTERNAL_KEY:
        req.add_header("X-Internal-Key", INTERNAL_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except Exception as e:
        log(f"POST {path} failed: {e}")
        return None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Drift detection started ==========")

    # 1. Fetch today's plan
    plan = api_get(f"/api/dailyos/plans/today?space_id={SPACE_ID}&context=default")
    if not plan:
        log("No plan found for today — skipping")
        log("========== Drift detection complete ==========")
        return

    # 2. Calculate completion
    items = plan.get("items", [])
    total = len(items)
    if total == 0:
        log("Plan has no items — skipping")
        log("========== Drift detection complete ==========")
        return

    done = sum(1 for it in items if it.get("completed") or it.get("done"))
    explicit_score = plan.get("completion_score")
    score = explicit_score if explicit_score is not None else (done / total * 100)

    log(f"Plan: {done}/{total} done, score={score:.0f}%")

    # 3. Check drift
    if score >= DRIFT_THRESHOLD:
        log(f"On track ({score:.0f}% >= {DRIFT_THRESHOLD}%) — no notification")
        log("========== Drift detection complete ==========")
        return

    # 4. Send notification
    today_str = date.today().isoformat()
    payload = {
        "category": "agent",
        "title": "Daily Drift",
        "body": f"進度：{score:.0f}%（{done}/{total} 完成）",
        "url": "/apps/dailyos",
        "severity": "warning",
        "tag": f"drift-{today_str}",
    }

    status = api_post("/api/notification/send", payload)
    if status and 200 <= status < 300:
        log(f"Notification sent (status={status})")
    else:
        log(f"Notification failed (status={status})")

    log("========== Drift detection complete ==========")


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()
