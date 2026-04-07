#!/usr/bin/env python3
"""
ws_memvault_dream.py — Daily 4AM dream consolidation

Calls POST /api/memvault/dream to run the 4-phase Dream Loop:
  Orient → Gather Signal → Consolidate → Prune & Report

The dual-gate trigger (24h + 5 sessions) is checked server-side.
If not met, the run is skipped gracefully.

Logs: ~/workshop/outputs/memvault/logs/dream.log
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
LOG_FILE = LOG_DIR / "dream.log"
CORE_API = "http://localhost:10000/api/memvault"
SPACE_ID = "default"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[dream] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def api_post(url: str) -> tuple[int | None, dict | None]:
    """POST with empty body; returns (status_code, response_json)."""
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            status = resp.status
            body = json.loads(resp.read())
            return status, body
    except urllib.error.HTTPError as e:
        log(f"HTTP error {e.code}: {e.reason}")
        return e.code, None
    except Exception as e:
        log(f"Request failed: {e}")
        return None, None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Dream consolidation started ==========")

    url = f"{CORE_API}/dream?space_id={SPACE_ID}&dry_run=false&force=false"
    log(f"POST {url}")

    status, body = api_post(url)

    if status == 200 and body is not None:
        if body.get("skipped"):
            orient = body.get("phase_orient", {})
            log(
                f"SKIPPED: dual-gate not met "
                f"(hours={orient.get('hours_since', '?')}, "
                f"sessions={orient.get('sessions_since', '?')})"
            )
        else:
            cons = body.get("phase_consolidate", {})
            prune = body.get("phase_prune", {})
            errors = body.get("errors", [])
            # Log consolidation summary
            log(
                f"OK: contradictions={cons.get('contradictions_resolved', 0)} "
                f"merged={cons.get('blocks_merged', 0)} "
                f"normalized={cons.get('content_normalized', 0)} "
                f"pruned={prune.get('curate', {}).get('blocks_soft_deleted', 0)} "
                f"errors={len(errors)}"
            )
            # Log reflection insights
            reflect = body.get("phase_reflect", {})
            if reflect and not reflect.get("error"):
                score = reflect.get("health_score", 0)
                log(f"  Reflect: health={score:.0%}")
                for insight in reflect.get("insights", [])[:5]:
                    log(f"    - {insight}")
                gaps = reflect.get("knowledge_gaps", [])
                if gaps:
                    log(f"  Gaps: {', '.join(gaps[:3])}")
            if errors:
                for e in errors:
                    log(f"  ERROR: {e}")
    else:
        log(f"FAILED: status={status} body={body}")
        sys.exit(1)

    log("========== Dream consolidation complete ==========")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
