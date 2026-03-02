#!/usr/bin/env python3
"""Confidence Decay Pipeline — periodic job to decay stale knowledge.

Run weekly via launchd or cron:
  python3 ~/workshop/mcp/memvault/pipelines/confidence_decay_pipeline.py

Calls Core API POST /api/memvault/kg/decay to apply exponential decay
to attitude fact confidence scores based on category-specific half-lives.

Half-life reference (configured in Core):
  technical     = 180 days
  preference    = 90  days
  principle     = 36500 days (~100 years, effectively permanent)
  workflow      = 120 days
  tool_behavior = 150 days
  config        = 120 days
  architecture  = 365 days
  default       = 180 days

Logs to: ~/Claude/memvault/logs/confidence-decay.log
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "confidence-decay.log"


# ── Logging ────────────────────────────────────────────────────────────────────
def setup_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(level: str, message: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] [{level}] {message}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        print(f"[WARN] Could not write to log file: {exc}", flush=True)


# ── HTTP helper (stdlib only) ───────────────────────────────────────────────────
def http_post(url: str, params: dict | None = None) -> dict:
    """POST with optional query-string params; returns parsed JSON."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        data=b"",  # empty body — all params are in query string
        method="POST",
        headers={"Accept": "application/json", "Content-Length": "0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> int:
    setup_log()
    log("INFO", f"Starting confidence decay pipeline (space_id={SPACE_ID})")

    decay_url = f"{CORE_API}/api/memvault/kg/decay"
    try:
        result = http_post(decay_url, params={"space_id": SPACE_ID})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log("ERROR", f"HTTP {exc.code} from Core API: {body}")
        return 1
    except urllib.error.URLError as exc:
        log("ERROR", f"Could not reach Core API at {CORE_API}: {exc.reason}")
        return 1
    except json.JSONDecodeError as exc:
        log("ERROR", f"Invalid JSON response from Core API: {exc}")
        return 1

    attitudes_checked = result.get("attitudes_checked", "?")
    attitudes_updated = result.get("attitudes_updated", "?")
    log(
        "INFO",
        f"Decay complete — checked={attitudes_checked} updated={attitudes_updated}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
