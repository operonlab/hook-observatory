#!/usr/bin/env python3
"""
ws_memvault_extract.py — Daily 3AM batch extraction + re-embedding

Pipeline:
  1. re_extract_batch.py --priority P0 (extract never-processed sessions)
  2. memvault_re_embed.py --missing-only (embed new blocks)

Runs before synthesis (4AM) so new blocks are available for clustering.
Logs: ~/workshop/outputs/memvault/logs/extract-batch.log
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# ── Quota Gate ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.quota_gate import request_clearance
from lib.structured_run import structured_run

request_clearance("ws-memvault-extract")

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
EXTRACT_SCRIPT = HOME / "workshop/mcp/memvault/scripts/re_extract_batch.py"
EMBED_SCRIPT = HOME / "workshop/core/scripts/memvault_re_embed.py"
PYTHON = HOME / ".local/bin/python3"
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "extract-batch.log"

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)
# Set PYTHONPATH for workshop imports
os.environ["PYTHONPATH"] = str(HOME / "workshop/core/src")
# LLM config: Gemini Flash for extraction (cheapest, best keyword compliance)
os.environ.setdefault("MEMVAULT_LLM", "gemini")
os.environ.setdefault("MEMVAULT_MODEL", "gemini-2.5-flash")
os.environ.setdefault("MEMVAULT_REFINE", "0")
os.environ["MEMVAULT_SKIP_RECALL"] = "1"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[extract-batch] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("========== Daily extraction started ==========")

    # Step 1: Extract P0 sessions (never extracted)
    log("Step 1/2: re_extract_batch.py --priority P0 --parallel 2")
    r1 = structured_run(
        [str(PYTHON), str(EXTRACT_SCRIPT), "--priority", "P0", "--parallel", "2"],
        label="memvault-extract-step1",
        timeout=3600,
    )
    log("Step 1 OK" if r1.success else f"Step 1 FAILED (exit {r1.returncode})")

    # Step 2: Embed any new blocks missing embeddings
    log("Step 2/2: memvault_re_embed.py --missing-only")
    r2 = structured_run(
        [str(PYTHON), str(EMBED_SCRIPT), "--missing-only"],
        label="memvault-extract-step2",
        timeout=600,
    )
    log("Step 2 OK" if r2.success else f"Step 2 FAILED (exit {r2.returncode})")

    log("========== Daily extraction complete ==========")


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
