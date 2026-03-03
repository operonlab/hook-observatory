"""Memory Guardian — pressure-based process management.

Ported from Pulso sysmon guardian.py. Monitors kern.memorystatus_level
and kills processes in priority order when memory pressure is detected.

Safety: double-check pressure, 30s cooldown, age protection, audit trail.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime

import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

_last_guardian_run: float = 0.0
_crit_streak: int = 0


def maybe_run_guardian(pressure: int) -> None:
    """Evaluate memory pressure and run guardian if needed."""
    global _last_guardian_run, _crit_streak

    now = time.time()

    if now - _last_guardian_run < settings.GUARDIAN_COOLDOWN:
        return

    fresh_pressure = _read_pressure()
    if fresh_pressure is None or fresh_pressure >= settings.GUARDIAN_WARN_THRESHOLD:
        _crit_streak = 0
        return

    _last_guardian_run = now

    is_crit_reading = fresh_pressure < settings.GUARDIAN_CRIT_THRESHOLD
    if is_crit_reading:
        _crit_streak += 1
    else:
        _crit_streak = 0

    sustained_crit = _crit_streak >= settings.GUARDIAN_SUSTAINED_CHECKS
    level = "CRIT" if sustained_crit else "WARN"

    log.warning(
        "guardian_triggered", level=level, pressure=fresh_pressure,
        crit_streak=_crit_streak,
    )

    actions: list[dict] = []

    # P1: Expendable apps (WARN + CRIT)
    actions.extend(_kill_expendables(fresh_pressure, level))

    # P2 + P3: Claude Code (CRIT only)
    if level == "CRIT":
        actions.extend(_kill_claude_code(fresh_pressure, level))

    if actions:
        _save_actions(actions)

    log.info("guardian_complete", level=level, actions=len(actions))


def _read_pressure() -> int | None:
    try:
        result = subprocess.run(
            ["sysctl", "-n", "kern.memorystatus_level"],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip())
    except Exception:
        return None


def _safe_kill(pid: int, sig: int = signal.SIGTERM) -> str:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "already_dead"
    except PermissionError:
        return "failed"

    try:
        os.kill(pid, sig)
        return "success"
    except ProcessLookupError:
        return "already_dead"
    except PermissionError:
        return "failed"


def _kill_expendables(pressure: int, level: str) -> list[dict]:
    """P1: Kill expendable apps, sorted by RSS descending."""
    actions = []

    for proc_pattern, display_name in settings.expendable_list:
        procs = _find_processes_by_name(proc_pattern)
        procs.sort(key=lambda p: p["rss_kb"], reverse=True)

        for p in procs:
            result = _safe_kill(p["pid"])
            mem_mb = p["rss_kb"] / 1024
            actions.append({
                "id": uuid.uuid4().hex,
                "ts": datetime.now(UTC).isoformat(),
                "level": level,
                "priority": "P1",
                "pid": p["pid"],
                "process_name": display_name,
                "mem_mb": round(mem_mb, 1),
                "cpu_pct": p.get("cpu", 0.0),
                "action": "TERM",
                "result": result,
                "detail": None,
            })
            log.info(
                "guardian_kill", priority="P1", name=display_name,
                pid=p["pid"], mem_mb=int(mem_mb), result=result,
            )

    return actions


def _kill_claude_code(pressure: int, level: str) -> list[dict]:
    """P2: Kill idle Claude. P3: Kill active Claude with grace period."""
    actions = []
    now_epoch = time.time()

    for p in _find_claude_processes():
        age = now_epoch - p["start_epoch"]

        if age < settings.GUARDIAN_MIN_AGE:
            actions.append({
                "id": uuid.uuid4().hex,
                "ts": datetime.now(UTC).isoformat(),
                "level": level, "priority": "P2",
                "pid": p["pid"], "process_name": "Claude Code",
                "mem_mb": round(p["rss_kb"] / 1024, 1),
                "cpu_pct": p["cpu"], "action": "SKIP",
                "result": "skipped",
                "detail": f"too_young_{int(age)}s",
            })
            continue

        mem_mb = p["rss_kb"] / 1024

        if p["cpu"] < settings.GUARDIAN_IDLE_CPU:
            result = _safe_kill(p["pid"])
            actions.append({
                "id": uuid.uuid4().hex,
                "ts": datetime.now(UTC).isoformat(),
                "level": level, "priority": "P2",
                "pid": p["pid"], "process_name": "Claude Code (idle)",
                "mem_mb": round(mem_mb, 1), "cpu_pct": p["cpu"],
                "action": "TERM", "result": result, "detail": None,
            })
            log.info("guardian_kill", priority="P2", pid=p["pid"], result=result)
        else:
            result = _safe_kill(p["pid"])
            actions.append({
                "id": uuid.uuid4().hex,
                "ts": datetime.now(UTC).isoformat(),
                "level": level, "priority": "P3",
                "pid": p["pid"], "process_name": "Claude Code (active)",
                "mem_mb": round(mem_mb, 1), "cpu_pct": p["cpu"],
                "action": "TERM", "result": result,
                "detail": f"grace_{settings.GUARDIAN_GRACE_SECONDS}s",
            })
            log.warning("guardian_kill", priority="P3", pid=p["pid"], result=result)
            if result == "success":
                threading.Thread(
                    target=_grace_kill,
                    args=(p["pid"], settings.GUARDIAN_GRACE_SECONDS),
                    daemon=True,
                ).start()

    return actions


def _grace_kill(pid: int, grace_seconds: int) -> None:
    time.sleep(grace_seconds)
    try:
        os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
        log.warning("guardian_force_kill", pid=pid)
    except ProcessLookupError:
        pass
    except PermissionError:
        log.warning("guardian_force_kill_denied", pid=pid)


def _find_processes_by_name(pattern: str) -> list[dict]:
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,rss=,%cpu=,command="],
            capture_output=True, text=True, timeout=5,
        ).stdout

        procs = []
        for line in output.splitlines():
            if pattern in line and "grep" not in line:
                parts = line.split(None, 3)
                if len(parts) >= 3:
                    procs.append({
                        "pid": int(parts[0]),
                        "rss_kb": int(parts[1]),
                        "cpu": float(parts[2]),
                    })
        return procs
    except Exception:
        return []


def _find_claude_processes() -> list[dict]:
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,rss=,%cpu=,lstart=,comm="],
            capture_output=True, text=True, timeout=5,
        ).stdout

        procs = []
        for line in output.splitlines():
            parts = line.split()
            if not parts:
                continue
            comm = parts[-1]
            if comm != "claude":
                continue

            pid = int(parts[0])
            rss_kb = int(parts[1])
            cpu = float(parts[2])

            try:
                lstart_str = " ".join(parts[3:8])
                from datetime import datetime as dt

                start_time = dt.strptime(lstart_str, "%c")
                start_epoch = start_time.timestamp()
            except Exception:
                start_epoch = 0

            procs.append({
                "pid": pid, "rss_kb": rss_kb,
                "cpu": cpu, "start_epoch": start_epoch,
            })
        return procs
    except Exception:
        return []


def _save_actions(actions: list[dict]) -> None:
    """Batch save guardian actions to database via asyncpg (sync wrapper)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_save_actions(actions))
    except RuntimeError:
        log.warning("guardian_save_no_loop", count=len(actions))


async def _async_save_actions(actions: list[dict]) -> None:
    try:
        from agent_metrics.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as con:
            await con.executemany(
                "INSERT INTO guardian_actions "
                "(id, ts, level, priority, pid, process_name, "
                "mem_mb, cpu_pct, action, result, detail) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                [
                    (
                        a["id"],
                        datetime.fromisoformat(a["ts"]),
                        a["level"],
                        a["priority"],
                        a["pid"],
                        a["process_name"],
                        a["mem_mb"],
                        a.get("cpu_pct"),
                        a["action"],
                        a["result"],
                        a.get("detail"),
                    )
                    for a in actions
                ],
            )
        log.info("guardian_actions_saved", count=len(actions))
    except Exception:
        log.exception("guardian_actions_save_error")
