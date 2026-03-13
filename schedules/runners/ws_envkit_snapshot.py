#!/usr/bin/env python3
"""
ws_envkit_snapshot.py — Weekly environment snapshot + config backup + drift detection

Pipeline (sequential):
  1. envkit snapshot  — capture full environment state
  2. envkit backup    — backup Tier 1-2 config files
  3. envkit diff      — compare with previous snapshot (drift detection)
  4. Rotate old snapshots (keep last 12)

Logs: ~/workshop/outputs/scheduler/logs/ws-envkit-snapshot.log
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
ENVKIT_DIR = HOME / "workshop/stations/envkit"
PYTHON = HOME / ".local/bin/python3"
SNAPSHOT_DIR = ENVKIT_DIR / "snapshots"
CONFIGS_DIR = ENVKIT_DIR / "configs"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-envkit-snapshot.log"
MAX_SNAPSHOTS = 12

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[envkit] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_envkit(args: list[str], capture: bool = False) -> tuple[bool, str]:
    """Run envkit.py with given args, appending output to log. Returns (success, output)."""
    cmd = [str(PYTHON), str(ENVKIT_DIR / "envkit.py")] + args
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Also append to log
        with open(LOG_FILE, "a") as f:
            if result.stdout:
                f.write(result.stdout)
            if result.stderr:
                f.write(result.stderr)
        return result.returncode == 0, result.stdout + result.stderr
    else:
        with open(LOG_FILE, "a") as f:
            result = subprocess.run(cmd, stdout=f, stderr=f)
        return result.returncode == 0, ""


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    log("========== EnvKit snapshot started ==========")

    # Find the most recent previous snapshot for diff
    existing_snapshots = sorted(SNAPSHOT_DIR.glob("mac-mini-*.yaml"), reverse=True)
    prev_snapshot = existing_snapshots[0] if existing_snapshots else None

    today = datetime.now().strftime("%Y-%m-%d")
    current_snapshot = SNAPSHOT_DIR / f"mac-mini-{today}.yaml"

    # Step 1: Take snapshot
    log("Step 1/4: envkit snapshot")
    success, _ = run_envkit(["snapshot", "--output", str(current_snapshot)])
    if success:
        log(f"Step 1 OK — saved to {current_snapshot}")
    else:
        log("Step 1 FAILED — aborting")
        sys.exit(1)

    # Step 2: Backup configs
    log("Step 2/4: envkit backup")
    success, _ = run_envkit(["backup", "--output-dir", str(CONFIGS_DIR)])
    if success:
        log(f"Step 2 OK — configs backed up to {CONFIGS_DIR}")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Diff with previous snapshot (drift detection)
    log("Step 3/4: drift detection")
    if prev_snapshot is not None and prev_snapshot.exists() and prev_snapshot != current_snapshot:
        success, diff_output = run_envkit(
            ["diff", str(prev_snapshot), str(current_snapshot)], capture=True
        )
        if success:
            lower_output = diff_output.lower()
            if any(kw in lower_output for kw in ("no differences", "identical", "0 changes")):
                log(f"  No drift detected since {prev_snapshot.name}")
            else:
                log(f"  Drift detected since {prev_snapshot.name}:")
                # Log first 30 lines of diff
                lines = diff_output.splitlines()[:30]
                with open(LOG_FILE, "a") as f:
                    for line in lines:
                        f.write(line + "\n")
                log("  (see log for details)")
        else:
            log("  Diff command failed")
        log("Step 3 OK")
    else:
        log("Step 3 SKIP — no previous snapshot to compare")

    # Step 4: Rotate old snapshots (keep last N)
    log(f"Step 4/4: rotate snapshots (keep last {MAX_SNAPSHOTS})")
    all_snapshots = sorted(SNAPSHOT_DIR.glob("mac-mini-*.yaml"), reverse=True)
    snapshot_count = len(all_snapshots)

    if snapshot_count > MAX_SNAPSHOTS:
        remove_count = snapshot_count - MAX_SNAPSHOTS
        to_remove = all_snapshots[MAX_SNAPSHOTS:]  # oldest are at the end (sorted reverse)
        for old in to_remove:
            old.unlink()
            log(f"  Removed old snapshot: {old.name}")
        log(f"  Rotated: removed {remove_count} old snapshots")
    else:
        log(f"  No rotation needed ({snapshot_count}/{MAX_SNAPSHOTS})")

    log("========== EnvKit snapshot complete ==========")


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
