"""Sysmon background loop — periodic collection + file output + history buffer.

Runs as an asyncio task, calling collect_all() via run_in_executor every N seconds.
Writes JSON to /tmp for tmux status line consumption and maintains an in-memory
ring buffer for the /sysmon/history API. Integrates quota data on each tick.
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

# Tick counter for periodic operations
_tick_count: int = 0


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
    global _latest_snapshot, _tick_count

    log.info("sysmon_loop_started", interval=settings.SYSMON_COLLECT_INTERVAL)

    loop = asyncio.get_running_loop()

    # Import here to avoid circular imports
    from agent_metrics.quota_collector import get_quota
    from agent_metrics.sse import sse_broadcast

    # Quota broadcast interval: broadcast quota every ~60s (12 ticks at 5s)
    _quota_tick_interval = max(1, 60 // settings.SYSMON_COLLECT_INTERVAL)

    try:
        while True:
            try:
                snapshot: SysmonSnapshot = await loop.run_in_executor(None, collect_all)
                snap_dict = snapshot.to_dict()

                # Track whether quota was refreshed this tick
                quota_refreshed = False

                # Merge quota data (60s TTL controlled internally)
                try:
                    quota = await get_quota()
                    for key in (
                        "llm_cc_5h",
                        "llm_cc_7d",
                        "llm_cc_ex",
                        "llm_cx_5h",
                        "llm_cx_7d",
                        "llm_gm_pro",
                        "llm_gm_flash",
                        "llm_display",
                    ):
                        if key in quota:
                            snap_dict[key] = quota[key]
                    quota_refreshed = True
                except Exception:
                    log.debug("quota_merge_failed", exc_info=True)

                # Update in-memory state
                _latest_snapshot = snap_dict
                _history_buffer.append(snap_dict)

                # Write to primary output path
                json_str = json.dumps(snap_dict)
                _atomic_write(settings.SYSMON_OUTPUT_PATH, json_str)

                # SSE: broadcast system metrics on every tick
                await sse_broadcast("system", snap_dict)

                # SSE: broadcast quota data every ~60s
                if quota_refreshed and _tick_count % _quota_tick_interval == 0:
                    quota_payload = {
                        k: snap_dict.get(k)
                        for k in (
                            "llm_cc_5h",
                            "llm_cc_7d",
                            "llm_cc_ex",
                            "llm_cx_5h",
                            "llm_cx_7d",
                            "llm_gm_pro",
                            "llm_gm_flash",
                            "llm_display",
                        )
                    }
                    await sse_broadcast("quota", quota_payload)

                # Guardian + Sweep (Phase 3)
                try:
                    from agent_metrics.guardian import maybe_run_guardian

                    await loop.run_in_executor(
                        None, maybe_run_guardian, snap_dict.get("mem_pressure", 99)
                    )
                except ImportError:
                    pass
                except Exception:
                    log.debug("guardian_tick_error", exc_info=True)

                _tick_count += 1
                sweep_ticks = settings.SWEEP_INTERVAL // settings.SYSMON_COLLECT_INTERVAL
                if sweep_ticks > 0 and _tick_count % sweep_ticks == 0:
                    try:
                        from agent_metrics.sweep import maybe_run_sweep

                        await loop.run_in_executor(None, maybe_run_sweep)
                    except ImportError:
                        pass
                    except Exception:
                        log.debug("sweep_tick_error", exc_info=True)

            except Exception:
                log.exception("sysmon_collect_error")

            await asyncio.sleep(settings.SYSMON_COLLECT_INTERVAL)

    except asyncio.CancelledError:
        log.info("sysmon_loop_stopped")
        raise
