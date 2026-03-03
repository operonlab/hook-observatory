"""Sysmon background loop — periodic collection + file output + history buffer.

Runs as an asyncio task, calling collect_all() via run_in_executor every N seconds.
Writes JSON to /tmp for tmux status line consumption and maintains an in-memory
ring buffer for the /sysmon/history API.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections import deque

import structlog

from agent_metrics.config import settings
from agent_metrics.sysmon_collector import SysmonSnapshot, collect_all

log = structlog.get_logger()

# In-memory latest snapshot (read by API routes)
_latest_snapshot: dict = {}

# Ring buffer for history (default 720 = 1h @ 5s interval)
_history_buffer: deque[dict] = deque(maxlen=settings.SYSMON_HISTORY_SIZE)


def get_latest() -> dict:
    """Return the latest sysmon snapshot dict."""
    return _latest_snapshot


def get_history(minutes: int = 60) -> list[dict]:
    """Return history entries within the last N minutes."""
    if minutes <= 0:
        return []
    max_entries = min(len(_history_buffer), minutes * 60 // settings.SYSMON_COLLECT_INTERVAL)
    return list(_history_buffer)[-max_entries:]


def _atomic_write(path: str, data: str) -> None:
    """Atomically write data to a file (write to tmp + rename)."""
    dir_path = os.path.dirname(path)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except OSError:
        log.warning("atomic_write_failed", path=path, exc_info=True)


async def sysmon_loop() -> None:
    """Background loop: collect system metrics every SYSMON_COLLECT_INTERVAL seconds."""
    global _latest_snapshot

    log.info("sysmon_loop_started", interval=settings.SYSMON_COLLECT_INTERVAL)

    loop = asyncio.get_running_loop()

    try:
        while True:
            try:
                snapshot: SysmonSnapshot = await loop.run_in_executor(None, collect_all)
                snap_dict = snapshot.to_dict()

                # Update in-memory state
                _latest_snapshot = snap_dict
                _history_buffer.append(snap_dict)

                # Write to primary output path
                json_str = json.dumps(snap_dict)
                _atomic_write(settings.SYSMON_OUTPUT_PATH, json_str)

                # Backward-compatible write (Pulso sysmon path)
                if settings.SYSMON_COMPAT_PATH:
                    _atomic_write(settings.SYSMON_COMPAT_PATH, json_str)

            except Exception:
                log.exception("sysmon_collect_error")

            await asyncio.sleep(settings.SYSMON_COLLECT_INTERVAL)

    except asyncio.CancelledError:
        log.info("sysmon_loop_stopped")
        raise
