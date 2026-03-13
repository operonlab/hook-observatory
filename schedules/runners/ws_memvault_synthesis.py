#!/usr/bin/env python3
"""
ws_memvault_synthesis.py — Daily 4AM knowledge graph synthesis

Pipeline (sequential, each step depends on the previous):
  1. cluster_pipeline.py  — re-cluster all triples (GMM)
  2. wisdom_pipeline.py   — synthesize cross-cluster wisdom (requires clusters)
  3. confidence_decay_pipeline.py — decay stale attitude confidence (independent)
  4. attitude_pipeline.py --all   — digest accumulated corrections
  5. Tag sync + domain auto-promotion (threshold >= 10)
  6. Reset triple counter (for threshold-based triggering)

Logs: ~/workshop/outputs/memvault/logs/synthesis.log
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

# ── Quota Gate ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.quota_gate import request_clearance

request_clearance("ws-memvault-synthesis")

# ── Memory Guardian ───────────────────────────────────────────
MEMORY_THRESHOLD = 85  # 記憶體使用率超過 85% 時停止執行


def check_memory_pressure() -> bool:
    """檢查記憶體壓力，超過閾值返回 False"""
    if psutil is None:
        return True  # 沒有 psutil 則預設允許執行
    memory_percent = psutil.virtual_memory().percent
    if memory_percent > MEMORY_THRESHOLD:
        return False
    return True


# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PIPELINES_DIR = HOME / "workshop/mcp/memvault/pipelines"
PYTHON = HOME / ".local/bin/python3"
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "synthesis.log"
CORRECTIONS_DIR = HOME / "workshop/outputs/memvault/corrections"
COUNTER_FILE = HOME / ".memvault-triple-counter"
CORE_API = "http://localhost:8801/api/memvault"
DOMAIN_THRESHOLD = 10

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[synthesis] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_pipeline(script_name: str, extra_args: list[str] | None = None) -> bool:
    """Run a pipeline script, appending output to log file. Returns True on success."""
    cmd = [str(PYTHON), str(PIPELINES_DIR / script_name)]
    if extra_args:
        cmd.extend(extra_args)
    with open(LOG_FILE, "a") as f:
        result = subprocess.run(cmd, stdout=f, stderr=f)
    return result.returncode == 0


def api_get(url: str) -> dict | list | None:
    """Perform a GET request and return parsed JSON, or None on error."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def api_post(url: str, data: dict) -> int | None:
    """Perform a POST request with JSON body. Returns HTTP status code or None on error."""
    try:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception:
        return None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Memory pressure check
    if not check_memory_pressure():
        mem_percent = psutil.virtual_memory().percent if psutil else "unknown"
        log(
            f"ABORT: Memory pressure too high ({mem_percent}% > {MEMORY_THRESHOLD}%), skipping synthesis"
        )
        sys.exit(0)

    log("========== Daily synthesis started ==========")

    # Step 1: Cluster pipeline (GMM re-clustering)
    log("Step 1/6: cluster_pipeline.py")
    if run_pipeline("cluster_pipeline.py"):
        log("Step 1 OK")
    else:
        log("Step 1 FAILED — continuing anyway")

    # Step 2: Wisdom pipeline (depends on fresh clusters)
    log("Step 2/6: wisdom_pipeline.py (timeout=600s)")
    if run_pipeline("wisdom_pipeline.py", ["--timeout", "600"]):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Confidence decay (independent of clusters/wisdom)
    log("Step 3/6: confidence_decay_pipeline.py")
    if run_pipeline("confidence_decay_pipeline.py"):
        log("Step 3 OK")
    else:
        log("Step 3 FAILED — continuing anyway")

    # Step 4: Attitude pipeline — digest all accumulated corrections
    log("Step 4/6: attitude_pipeline.py --all")
    if CORRECTIONS_DIR.is_dir():
        if run_pipeline("attitude_pipeline.py", ["--input", str(CORRECTIONS_DIR), "--all"]):
            log("Step 4 OK")
        else:
            log("Step 4 FAILED — continuing anyway")
    else:
        log("Step 4 SKIP — no corrections directory")

    # Step 5: Tag sync + domain auto-promotion
    log("Step 5/6: Tag sync + domain promotion")

    # Tag sync via POST
    try:
        req = urllib.request.Request(
            f"{CORE_API}/tags/sync?space_id=default",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sync_result = resp.read().decode()
        log(f"  Tags synced: {sync_result}")
    except Exception as e:
        log(f"  Tag sync failed (API unreachable? {e})")

    # Auto-promote tags with usage >= threshold to knowledge domains
    promoted = 0
    tags_data = api_get(f"{CORE_API}/tags?space_id=default")
    domains_data = api_get(f"{CORE_API}/domains?space_id=default&page_size=200")

    if tags_data is not None and domains_data is not None:
        existing_domains = {d["name"] for d in domains_data.get("items", [])}
        tags = tags_data if isinstance(tags_data, list) else tags_data.get("items", [])
        new_tags = [
            t
            for t in tags
            if t.get("usage_count", 0) >= DOMAIN_THRESHOLD and t["name"] not in existing_domains
        ]
        for t in new_tags:
            status = api_post(
                f"{CORE_API}/domains?space_id=default",
                {
                    "name": t["name"],
                    "description": f"Auto-promoted (usage: {t['usage_count']})",
                },
            )
            if status == 201:
                promoted += 1

    log(f"  Domains promoted: {promoted} new (threshold >= {DOMAIN_THRESHOLD})")
    log("Step 5 OK")

    # Step 6: Reset triple counter
    log("Step 6/6: Reset triple counter")
    COUNTER_FILE.write_text("0\n")
    log("Triple counter reset to 0")

    log("========== Daily synthesis complete ==========")


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
