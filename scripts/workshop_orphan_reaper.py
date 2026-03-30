#!/usr/bin/env python3
"""
workshop_orphan_reaper.py — Detect and clean orphaned workshop processes.

Scans for processes whose command contains 'workshop/' but are orphaned (PPID=1)
and not tracked by any known manager (workshop_services PID files, launchd, etc.).

Usage:
    python3 workshop_orphan_reaper.py              # dry-run (report only)
    python3 workshop_orphan_reaper.py --kill        # SIGTERM orphans
    python3 workshop_orphan_reaper.py --json        # JSON output for integration
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

PID_DIR = Path("/opt/homebrew/var/run/workshop")

# Processes with PPID=1 that are legitimately managed (not orphans).
# These are started by launchd scheduler plists or workshop-launcher.
KNOWN_MANAGED_COMMANDS = {
    # workshop-launcher starts workshop_services.py which daemonizes children
    "workshop_services.py",
    # Cronicle runners (short-lived, PPID=1 after Cronicle forks)
    "ws_memory_guardian.py",
    "ws_relay_reaper",
}

# Process names that should never be killed even if they look orphaned.
PROTECTED_PATTERNS = {
    "uvicorn src.main:app",  # workshop core (managed by workshop_services)
    "workshop_services.py",  # the service manager itself
    "sentinel",  # health checker
}


def _get_managed_pids() -> set[int]:
    """Read PIDs from workshop_services PID directory."""
    pids: set[int] = set()
    if PID_DIR.exists():
        for pidfile in PID_DIR.glob("*.pid"):
            try:
                pid = int(pidfile.read_text().strip())
                pids.add(pid)
            except (ValueError, OSError):
                pass
    return pids


def _get_workshop_processes() -> list[dict]:
    """Get all processes with 'workshop/' in their command."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,pgid,rss,etime,command"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    procs = []
    for line in result.stdout.strip().split("\n")[1:]:  # skip header
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid_s, ppid_s, pgid_s, rss_s, etime, command = parts
        if "workshop/" not in command:
            continue
        try:
            pid_i = int(pid_s)
            ppid_i = int(ppid_s)
            pgid_i = int(pgid_s)
        except ValueError:
            continue
        try:
            rss_mb = int(rss_s) // 1024
        except ValueError:
            rss_mb = 0  # ps may output '-' or '?' for RSS
        procs.append(
            {
                "pid": pid_i,
                "ppid": ppid_i,
                "pgid": pgid_i,
                "rss_mb": rss_mb,
                "etime": etime.strip(),
                "command": command.strip(),
            }
        )
    return procs


def _cmd_basename(cmd: str) -> str:
    """Extract the script basename from a command string."""
    # "python3 /path/to/script.py --args" → "script.py"
    for part in cmd.split():
        if part.endswith(".py"):
            return part.rsplit("/", 1)[-1]
    return ""


def find_orphans() -> list[dict]:
    """Identify orphaned workshop processes."""
    managed_pids = _get_managed_pids()
    managed_pids.add(os.getpid())  # never reap ourselves
    all_procs = _get_workshop_processes()
    orphans = []

    for proc in all_procs:
        # Only check PPID=1 (adopted by init = original parent died)
        if proc["ppid"] != 1:
            continue

        # Skip if tracked by workshop_services PID file
        if proc["pid"] in managed_pids:
            continue

        # Skip known managed commands (match by script basename, not substring)
        basename = _cmd_basename(proc["command"])
        if basename in KNOWN_MANAGED_COMMANDS:
            continue

        # Skip protected processes (substring match for compound patterns)
        cmd = proc["command"]
        if any(p in cmd for p in PROTECTED_PATTERNS):
            continue

        # Skip MCP server processes (managed by mcpproxy, transient)
        if "/mcp/" in cmd and "server.py" in cmd:
            continue

        # This looks like an orphan
        orphans.append(proc)

    return orphans


def main():
    parser = argparse.ArgumentParser(description="Workshop orphan process reaper")
    parser.add_argument("--kill", action="store_true", help="SIGTERM orphaned processes")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    orphans = find_orphans()

    if args.json:
        print(json.dumps({"orphans": orphans, "count": len(orphans)}))
        return

    if not orphans:
        print("No orphaned workshop processes found.")
        return

    print(f"Found {len(orphans)} orphaned workshop process(es):\n")
    for o in orphans:
        cmd = o["command"][:80]
        print(f"  PID {o['pid']:>6}  RSS {o['rss_mb']:>4} MB  uptime {o['etime']:>12}  {cmd}")

    if args.kill:
        print()
        for o in orphans:
            pid = o["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  SIGTERM → PID {pid} ✓")
            except ProcessLookupError:
                print(f"  PID {pid} already gone")
            except PermissionError:
                print(f"  PID {pid} permission denied")
    else:
        print("\nRun with --kill to terminate these processes.")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "schedules"))
    main()
