#!/usr/bin/env python3
"""ws_account_sync.py — Merged LLM provider account sync.

Replaces two daily jobs (``ws-provider-balance-sync`` + ``ws-dashscope-quota-sync``)
that each scraped a different set of LLM provider dashboards. Both
subcommands already live in the ``agent-metrics`` rust binary; this
runner just invokes them in sequence so they share a single launch
window and a single log file.

Order: balance first (covers MiniMax / Moonshot / Z.AI / DeepSeek / xAI),
then dashscope (Qwen free-quota). They write to disjoint Redis key
prefixes so order doesn't matter for correctness — sequencing just keeps
the log linear.

Exit code: non-zero if either subcommand failed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BIN = Path.home() / ".cargo/shared-target/release/agent-metrics"
LOG_FILE = Path.home() / "workshop/outputs/scheduler/logs/ws-account-sync.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SUBCOMMANDS = ("provider-balance-sync", "dashscope-quota-sync")


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001,S110 — log write is best-effort
        pass


def run_subcommand(subcmd: str, dry: bool) -> int:
    cmd = [str(BIN), subcmd]
    _log(f"subcommand={subcmd} cmd={' '.join(cmd)} dry_run={dry}")
    if dry:
        return 0
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        _log(
            f"  FAILED rc={proc.returncode} "
            f"stderr={proc.stderr.strip()[:300] if proc.stderr else '(empty)'}"
        )
    else:
        _log(f"  OK rc=0 stdout_lines={len(proc.stdout.splitlines())}")
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="log planned subcommands without invoking them"
    )
    args = parser.parse_args()

    _log("=== ws-account-sync start ===")
    if not BIN.is_file():
        _log(f"FATAL: agent-metrics binary not found at {BIN}")
        return 2

    worst_rc = 0
    for sub in SUBCOMMANDS:
        rc = run_subcommand(sub, args.dry_run)
        if rc != 0 and worst_rc == 0:
            worst_rc = rc
    _log(f"=== ws-account-sync done worst_rc={worst_rc} ===")
    return worst_rc


if __name__ == "__main__":
    sys.exit(main())
