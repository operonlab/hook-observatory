#!/Users/joneshong/.local/bin/python3
"""
ws_session_archive.py — Daily 5:45AM session lifecycle pipeline

Pipeline (sequential, fail-safe):
  1. redact sweep — catch any sessions missed by SessionEnd hook
  2. scan         — discover all sessions, update DB index
  3. archive      — compress cold candidates with summaries + embeddings
  4. reflect      — quality scoring for unreflected sessions

Design: 3-layer fallback strategy
  Layer 1 (real-time): SessionEnd hook → pipeline (redact → extract → archive → reflect → log)
  Layer 2 (daily):     This script — sweep all stages (catches hook failures)
  Layer 3 (manual):    SDK / CLI available anytime

Logs: ~/.claude/data/session-archiver/run.log
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
STATION_DIR = HOME / "workshop/stations/session-archiver"
LOG_DIR = HOME / ".claude/data/session-archiver"
LOG_FILE = LOG_DIR / "run.log"
UV = "/opt/homebrew/bin/uv"

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[session-archive] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_step(args: list[str]) -> bool:
    """Run a uv python module step, appending output to log. Returns True on success."""
    cmd = [UV, "run", "python", "-m"] + args
    with open(LOG_FILE, "a") as f:
        result = subprocess.run(cmd, stdout=f, stderr=f, cwd=str(STATION_DIR))
    return result.returncode == 0


def run_redact_sweep() -> bool:
    """Run session redactor full_sweep via SDK (in-process). Returns True on success."""
    try:
        sys.path.insert(0, str(HOME / "workshop/libs/sdk-client"))
        from sdk_client.session_redactor import SessionRedactorClient

        client = SessionRedactorClient()
        result = client.full_sweep(trigger="scheduled")
        log(
            f"  redact sweep: processed={result['files_processed']} "
            f"skipped={result['files_skipped']} "
            f"redactions={result['total_redactions']} "
            f"errors={result['errors']}"
        )
        return result["errors"] == 0
    except Exception as exc:
        log(f"  redact sweep error: {exc}")
        return False


def run_reflect_sweep() -> bool:
    """Run reflect engine on unreflected sessions via SDK (in-process)."""
    try:
        _libs = str(HOME / "workshop/libs/python/src")
        if _libs not in sys.path:
            sys.path.insert(0, _libs)
        _engine_dir = str(HOME / "workshop/stations/session-pipeline")
        if _engine_dir not in sys.path:
            sys.path.insert(0, _engine_dir)
        _archiver_src = str(HOME / "workshop/stations/session-archiver/src")
        if _archiver_src not in sys.path:
            sys.path.insert(0, _archiver_src)

        from reflect_engine import analyze_transcript
        from session_archiver.config import load_config
        from session_archiver.db import get_unreflected_session_ids, upsert_reflection

        config = load_config()

        unreflected = get_unreflected_session_ids(config, limit=50)
        if not unreflected:
            log("  reflect sweep: no unreflected sessions")
            return True

        reflected = 0
        for sid, project_path in unreflected:
            # Find transcript JSONL
            transcript = None
            if project_path:
                proj = Path(project_path) / ".claude"
                candidates = list(proj.glob(f"{sid}.jsonl"))
                if candidates:
                    transcript = str(candidates[0])

            if not transcript:
                continue

            try:
                from dataclasses import asdict

                metrics = analyze_transcript(transcript, sid)
                upsert_reflection(config, asdict(metrics))
                reflected += 1
            except Exception:
                continue

        log(f"  reflect sweep: reflected={reflected}/{len(unreflected)}")
        return True
    except Exception as exc:
        log(f"  reflect sweep error: {exc}")
        return False


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("========== Daily session lifecycle started ==========")

    # Step 1: Redact sweep — catch sessions missed by SessionEnd hook
    log("Step 1/6: Redact sweep...")
    if run_redact_sweep():
        log("Step 1 OK")
    else:
        log("Step 1 FAILED — continuing anyway (archive still runs)")

    # Step 2: Scan + warm promotion (generate summaries for aging sessions)
    log("Step 2/6: Scanning + warm promotion...")
    if run_step(["session_archiver", "scan", "--summarize", "--json"]):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Archive (execute mode, warm sessions skip summary generation)
    log("Step 3/6: Archiving cold candidates...")
    if run_step(["session_archiver", "archive", "--execute", "--summarize", "--embed", "--json"]):
        log("Step 3 OK")
    else:
        log("Step 3 FAILED — continuing anyway")

    # Step 4: Freeze — upload old cold archives to RustFS (S3)
    log("Step 4/6: Freezing old cold sessions...")
    if run_step(["session_archiver", "freeze", "--execute", "--json"]):
        log("Step 4 OK")
    else:
        log("Step 4 FAILED — continuing anyway (RustFS may be offline)")

    # Step 5: Reflect — quality scoring for unreflected sessions
    log("Step 5/6: Reflect sweep...")
    if run_reflect_sweep():
        log("Step 5 OK")
    else:
        log("Step 5 FAILED — continuing anyway")

    log("========== Daily session lifecycle complete ==========")


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
