#!/usr/bin/env python3
"""
ws_memvault_lint.py — Weekly Sunday 3:30AM knowledge graph health check

Calls POST /api/memvault/kg/lint?space_id=default to detect
contradictions, stale triples, orphan entities, and other issues.

Logs: ~/workshop/outputs/memvault/logs/lint.log
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "lint.log"
CORE_API = "http://localhost:10000/api/memvault"
SPACE_ID = "default"
INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[lint] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def api_post(url: str) -> tuple[int | None, dict | None]:
    """POST with empty body; returns (status_code, response_json)."""
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_KEY:
            headers["x-internal-key"] = INTERNAL_KEY
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        log(f"HTTP error {e.code}: {e.reason}")
        return e.code, None
    except Exception as e:
        log(f"Request failed: {e}")
        return None, None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Knowledge Lint started ==========")

    # Full lint (report only)
    url = f"{CORE_API}/kg/lint?space_id={SPACE_ID}&checks=all"
    log(f"POST {url}")
    status, data = api_post(url)
    if status != 200 or not data:
        log(f"Lint failed: status={status}")
        sys.exit(1)

    summary = data.get("summary", {})
    total = sum(summary.values())
    duration = data.get("run_duration_ms", 0)
    log(f"Results: {total} findings in {duration:.0f}ms — {summary}")

    # Auto-remediate safe categories (stale + orphans + semantic + knowledge_conflicts)
    if total > 0:
        fix_url = (
            f"{CORE_API}/kg/lint?space_id={SPACE_ID}"
            "&checks=stale,orphan_entities,semantic_contradictions,knowledge_conflicts"
            "&fix=true&dry_run=false"
        )
        log(f"POST {fix_url}")
        fix_status, fix_data = api_post(fix_url)
        if fix_status == 200 and fix_data:
            remediated = fix_data.get("remediations_applied", 0)
            log(f"Auto-remediated: {remediated} (stale + orphans)")
        else:
            log(f"Auto-remediation failed: status={fix_status}")

    log("========== Knowledge Lint complete ==========")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
