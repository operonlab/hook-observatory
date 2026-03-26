#!/usr/bin/env python3
"""
ws_memvault_attitude.py — Daily 5AM attitude corrections processing

Runs attitude_pipeline.py to evolve attitude facts from auto-collected corrections.
Notifies via Bark if high-drift corrections found.

Logs: ~/workshop/outputs/memvault/logs/attitude.log
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "attitude.log"
PYTHON = str(HOME / ".local" / "bin" / "python3")
PIPELINE_SCRIPT = str(HOME / "workshop" / "mcp" / "memvault" / "pipelines" / "attitude_pipeline.py")
CORRECTIONS_DIR = HOME / "Claude" / "memvault" / "corrections"
NOTIFY_API = "http://localhost:10000/api/notification"
SPACE_ID = "default"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[attitude] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Attitude corrections pipeline started ==========")

    # Check if corrections dir has any unprocessed JSONL files
    if not CORRECTIONS_DIR.is_dir():
        log(f"No corrections directory found at {CORRECTIONS_DIR}")
        log("========== Attitude pipeline complete (nothing to do) ==========")
        return

    jsonl_files = [f for f in CORRECTIONS_DIR.rglob("**/*.jsonl") if "processed" not in f.parts]
    if not jsonl_files:
        log("No unprocessed JSONL files found")
        log("========== Attitude pipeline complete (nothing to do) ==========")
        return

    log(f"Found {len(jsonl_files)} unprocessed JSONL file(s)")

    # Run attitude_pipeline.py with --all --archive --notify
    cmd = [
        PYTHON,
        PIPELINE_SCRIPT,
        "--input",
        str(CORRECTIONS_DIR),
        "--all",
        "--archive",
        "--notify",
        "--space-id",
        SPACE_ID,
    ]
    log(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                log(f"  {line}")
        if result.returncode != 0:
            log(f"Pipeline exited with code {result.returncode}")
            if result.stderr:
                log(f"stderr: {result.stderr[:500]}")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        log("Pipeline timed out after 120s")
        sys.exit(1)
    except Exception as e:
        log(f"Failed to run pipeline: {e}")
        sys.exit(1)

    # Check for notify summary
    notify_file = CORRECTIONS_DIR / "notify_summary.json"
    if notify_file.is_file():
        try:
            summary = json.loads(notify_file.read_text(encoding="utf-8"))
            high_drift = summary.get("high_drift_count", 0)
            if high_drift >= 2:
                log(f"High-drift corrections found: {high_drift}")
                _send_notification(summary)
            notify_file.unlink()
        except Exception as e:
            log(f"Failed to read notify summary: {e}")

    log("========== Attitude corrections pipeline complete ==========")


def _send_notification(summary: dict) -> None:
    """POST notification about high-drift attitude corrections."""
    try:
        body = {
            "title": "KAS Attitude 校準提醒",
            "message": (
                f"偵測到 {summary.get('high_drift_count', 0)} 筆重大態度校準\n"
                f"處理: {summary.get('ok', 0)} OK / {summary.get('fail', 0)} FAIL"
            ),
            "channel": "bark",
            "priority": "normal",
            "space_id": SPACE_ID,
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{NOTIFY_API}/send?space_id={SPACE_ID}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"Notification sent: HTTP {resp.status}")
    except Exception as e:
        log(f"Notification failed (non-fatal): {e}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
