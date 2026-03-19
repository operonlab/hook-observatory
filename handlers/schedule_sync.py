"""
Schedule sync handler — PostToolUse for Edit/Write on manifest.json.

Detects changes to schedules/manifest.json and triggers background sync
to launchd via sync.py (fire-and-forget, idempotent).
"""

from __future__ import annotations

import os
import sys

from .base import ALLOW, HookResult, run_background

HOME = os.path.expanduser("~")
WORKSHOP = os.path.join(HOME, "workshop")
PYTHON = os.path.join(HOME, ".local", "bin", "python3")
SYNC_SCRIPT = os.path.join(WORKSHOP, "schedules", "sync.py")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse handler: detect manifest.json writes and trigger sync."""
    file_path = tool_input.get("file_path", "")
    if "schedules/manifest.json" not in file_path:
        return ALLOW

    run_background([PYTHON, SYNC_SCRIPT], cwd=WORKSHOP)
    _log("manifest.json changed → sync triggered")
    return ALLOW


def _log(msg: str) -> None:
    print(f"[schedule-sync] {msg}", file=sys.stderr)
