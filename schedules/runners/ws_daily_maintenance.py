#!/usr/bin/env python3
"""
ws_daily_maintenance.py — Daily lightweight maintenance check

Pipeline:
  1. Run system-map drift check (baseline diff)
  2. Compare skill/MCP counts vs last snapshot
  3. Log results, Bark on drift or count mismatch

Designed for Cronicle daily schedule (16:30).
No LLM needed — pure mechanical checks.
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
DRIFT_SCRIPT = HOME / ".claude/skills/system-map/scripts/check_drift.py"
SKILLS_DIR = HOME / ".claude/skills"
MCP_DIR = HOME / "workshop/mcp"
OUTPUT_DIR = HOME / "workshop/outputs/maintenance"
COUNTS_FILE = OUTPUT_DIR / "last-counts.json"

BARK_URL = os.environ.get("BARK_URL", "http://127.0.0.1:8090")
BARK_KEY = os.environ.get("BARK_KEY", "")

os.environ["PATH"] = (
    f"{HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin"
    f":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def bark_notify(title: str, body: str) -> None:
    if not BARK_KEY:
        log("BARK_KEY not set, skip notification")
        return
    url = f"{BARK_URL}/{BARK_KEY}/{title}/{body}"
    try:
        urllib.request.urlopen(url, timeout=10)
        log(f"Bark sent: {title}")
    except Exception as e:
        log(f"Bark failed: {e}")


def run_drift_check() -> tuple[bool, str]:
    """Run drift check script. Returns (has_drift, output)."""
    try:
        result = subprocess.run(
            [str(PYTHON), str(DRIFT_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return result.returncode != 0, output
    except Exception as e:
        return True, f"Error running drift check: {e}"


def count_dirs(path: Path) -> int:
    """Count immediate subdirectories (excluding hidden)."""
    if not path.is_dir():
        return 0
    return sum(1 for d in path.iterdir() if d.is_dir() and not d.name.startswith("."))


def check_counts() -> tuple[bool, dict, dict]:
    """Compare skill/MCP counts vs last snapshot. Returns (changed, current, previous)."""
    current = {
        "skills": count_dirs(SKILLS_DIR),
        "mcp": count_dirs(MCP_DIR),
    }

    previous = {}
    if COUNTS_FILE.exists():
        try:
            previous = json.loads(COUNTS_FILE.read_text())
        except Exception:
            pass

    changed = current != previous

    # Always update counts file
    COUNTS_FILE.write_text(json.dumps(current, indent=2) + "\n")

    return changed, current, previous


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    log_file = OUTPUT_DIR / f"daily-{today}.log"
    results = []

    # ── Step 1: Drift check ──
    log("Step 1: Running drift check...")
    has_drift, drift_output = run_drift_check()

    if has_drift:
        results.append(f"⚠️ DRIFT DETECTED:\n{drift_output}")
        bark_notify("System Drift", drift_output[:80])
    else:
        results.append("✅ No drift")

    # ── Step 2: Count check ──
    log("Step 2: Checking skill/MCP counts...")
    changed, current, previous = check_counts()

    if changed and previous:
        diff_parts = []
        for key in current:
            if current[key] != previous.get(key, 0):
                diff_parts.append(f"{key}: {previous.get(key, '?')} → {current[key]}")
        diff_msg = ", ".join(diff_parts)
        results.append(f"📦 Counts changed: {diff_msg} — consider running /sync-config")
        bark_notify("Config Changed", diff_msg[:80])
    elif not previous:
        results.append(f"📦 Initial counts: skills={current['skills']}, mcp={current['mcp']}")
    else:
        results.append(f"✅ Counts stable: skills={current['skills']}, mcp={current['mcp']}")

    # ── Step 3: Write log ──
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n--- {ts} ---\n" + "\n".join(results) + "\n"

    with open(log_file, "a") as f:
        f.write(entry)

    for r in results:
        log(r)

    log(f"Results written to {log_file}")
    return 1 if has_drift else 0


if __name__ == "__main__":
    sys.exit(main())
