#!/usr/bin/env python3
"""
ws_memvault_synthesis.py — Daily knowledge graph synthesis

Pipeline (sequential):
  1. synthesis_runner.py — Leiden community detection + LLM summaries (3 levels)
     (also triggers Qdrant auto-indexing for L1/L2 via save_communities/save_summaries)
  2. confidence_decay_pipeline.py — decay stale attitude confidence
  3. attitude_pipeline.py --all   — digest accumulated corrections
  4. Tag sync + domain auto-promotion (threshold >= 10)
  5. Reset triple counter (for threshold-based triggering)

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

# ── Structured Run ─────────────────────────────────────────────

try:
    import psutil
except ImportError:
    psutil = None

# ── Quota Gate ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.quota_gate import request_clearance
from lib.structured_run import structured_run

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
UV = "/opt/homebrew/bin/uv"
CORE_PROJECT = HOME / "workshop/core"
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "synthesis.log"
CORRECTIONS_DIR = HOME / "workshop/outputs/memvault/corrections"
COUNTER_FILE = HOME / ".memvault-triple-counter"
CORE_API = "http://localhost:10000/api/memvault"
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

    # Step 1: Leiden community detection + LLM summaries (synthesis_runner.py)
    # This also triggers Qdrant auto-indexing for L1 communities and L2 summaries
    log("Step 1/5: synthesis_runner.py (Leiden + summaries)")
    step1 = structured_run(
        [
            str(UV),
            "run",
            "--project",
            str(CORE_PROJECT),
            str(PIPELINES_DIR / "synthesis_runner.py"),
        ],
        label="memvault-synthesis",
        timeout=2400,  # 3 levels × 600s + Leiden ~120s + margin
    )
    # 將 stdout 同時輸出到 log file（保持原本的記錄行為）
    if step1.stdout:
        with open(LOG_FILE, "a") as f:
            f.write(step1.stdout)
        print(step1.stdout, end="", flush=True)
    if step1.stderr:
        with open(LOG_FILE, "a") as f:
            f.write(step1.stderr)
    if step1.success:
        log(f"Step 1 OK ({step1.duration_seconds:.1f}s)")
    else:
        log(f"Step 1 FAILED (exit {step1.returncode}) — continuing anyway")

    # Step 2: Confidence decay (independent of communities)
    log("Step 2/5: confidence_decay_pipeline.py")
    if run_pipeline("confidence_decay_pipeline.py"):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Attitude pipeline — digest all accumulated corrections
    log("Step 3/5: attitude_pipeline.py --all")
    if CORRECTIONS_DIR.is_dir():
        if run_pipeline("attitude_pipeline.py", ["--input", str(CORRECTIONS_DIR), "--all"]):
            log("Step 3 OK")
        else:
            log("Step 3 FAILED — continuing anyway")
    else:
        log("Step 3 SKIP — no corrections directory")

    # Step 4: Tag sync + domain auto-promotion
    log("Step 4/5: Tag sync + domain promotion")

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
    log("Step 4 OK")

    # Step 5: Reset triple counter
    log("Step 5/5: Reset triple counter")
    COUNTER_FILE.write_text("0\n")
    log("Triple counter reset to 0")

    log("========== Daily synthesis complete ==========")


if __name__ == "__main__":
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
