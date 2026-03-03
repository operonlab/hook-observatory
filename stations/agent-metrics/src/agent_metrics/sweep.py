"""Process Sweep — periodic cleanup of stale/orphaned processes.

Ported from Pulso sysmon process_sweep.py. Proactive 30-min sweeps:
- MCP orphans (ppid=1)
- Zombies (Z-state → SIGCHLD)
- CPU hogs (ppid=1, >80%, >10min)
- Stale Node.js (ppid=1, >48h kill)
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

_last_sweep: float = 0.0

# MCP pattern cache
_mcp_patterns_cache: tuple[float, list[str]] = (0.0, [])
MCP_CACHE_TTL = 300


def maybe_run_sweep() -> None:
    """Run process sweep if enough time has passed."""
    global _last_sweep

    now = time.time()
    if now - _last_sweep < settings.SWEEP_INTERVAL:
        return

    _last_sweep = now
    log.info("sweep_started")

    actions: list[dict] = []
    actions.extend(_sweep_mcp_orphans())
    actions.extend(_sweep_zombies())
    actions.extend(_sweep_cpu_hogs())
    actions.extend(_sweep_stale_node())

    if actions:
        _save_actions(actions)

    log.info("sweep_complete", cleaned=len(actions))


# ---------------------------------------------------------------------------
# MCP Dynamic Pattern Loading
# ---------------------------------------------------------------------------

def _load_mcp_patterns() -> list[str]:
    global _mcp_patterns_cache

    now = time.time()
    cached_ts, cached_patterns = _mcp_patterns_cache
    if cached_patterns and (now - cached_ts) < MCP_CACHE_TTL:
        return cached_patterns

    patterns: set[str] = set()

    for config_path in settings.MCP_CONFIG_PATHS:
        expanded = Path(config_path).expanduser()
        try:
            data = json.loads(expanded.read_text())
            servers = data.get("mcpServers", {})
            patterns.update(servers.keys())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue

    patterns.update(settings.mcp_pattern_list)

    result = sorted(patterns)
    _mcp_patterns_cache = (now, result)
    return result


# ---------------------------------------------------------------------------
# Sweep Functions
# ---------------------------------------------------------------------------

def _sweep_mcp_orphans() -> list[dict]:
    """Kill orphaned MCP server processes (ppid=1)."""
    actions = []
    has_active_claude = bool(_find_processes("claude"))
    mcp_patterns = _load_mcp_patterns()

    for pattern in mcp_patterns:
        candidates = _find_processes(pattern)

        for p in candidates:
            if has_active_claude:
                ppid = _get_ppid(p["pid"])
                if ppid != 1:
                    continue

            result = _safe_signal(p["pid"], signal.SIGTERM)
            actions.append(_make_action(
                priority="SWEEP-MCP",
                pid=p["pid"],
                process_name=f"mcp-orphan ({pattern})",
                mem_mb=round(p["rss_kb"] / 1024, 1),
                cpu_pct=p["cpu"],
                action="TERM",
                result=result,
                detail="ppid=1" if has_active_claude else "no_claude_parent",
            ))
            log.info("sweep_mcp_orphan", pid=p["pid"], pattern=pattern, result=result)

    return actions


def _sweep_cpu_hogs() -> list[dict]:
    """Kill orphaned processes stuck in infinite loops."""
    actions = []

    try:
        procs = _get_process_details()
    except Exception:
        log.exception("sweep_cpu_hogs_ps_error")
        return actions

    for p in procs:
        if p["ppid"] != 1:
            continue
        if p["pid"] < 100:
            continue
        if p["cpu"] < settings.SWEEP_CPU_THRESHOLD:
            continue
        if p["etime_sec"] < settings.SWEEP_CPU_MIN_AGE:
            continue
        if any(w in p["command"] for w in settings.SWEEP_CPU_WHITELIST):
            continue

        age_min = p["etime_sec"] // 60
        result = _safe_signal(p["pid"], signal.SIGTERM)
        actions.append(_make_action(
            priority="SWEEP-CPU",
            pid=p["pid"],
            process_name=p["command"][:80],
            mem_mb=round(p["rss_kb"] / 1024, 1),
            cpu_pct=p["cpu"],
            action="TERM",
            result=result,
            detail=f"cpu={p['cpu']}%,age={age_min}m",
        ))
        log.info("sweep_cpu_hog", pid=p["pid"], cpu=p["cpu"], age_min=age_min, result=result)

    return actions


def _sweep_stale_node() -> list[dict]:
    """Detect stale Node.js orphan processes."""
    actions = []
    warn_sec = settings.SWEEP_STALE_WARN_HOURS * 3600
    kill_sec = settings.SWEEP_STALE_KILL_HOURS * 3600

    try:
        procs = _get_process_details()
    except Exception:
        log.exception("sweep_stale_node_ps_error")
        return actions

    for p in procs:
        if p["ppid"] != 1:
            continue
        if not re.search(r"(?:^|/)node\s", p["command"]):
            continue
        if any(w in p["command"] for w in settings.SWEEP_STALE_WHITELIST):
            continue

        age_hours = p["etime_sec"] / 3600

        if p["etime_sec"] > kill_sec:
            result = _safe_signal(p["pid"], signal.SIGTERM)
            actions.append(_make_action(
                priority="SWEEP-STALE-NODE",
                pid=p["pid"],
                process_name=p["command"][:80],
                mem_mb=round(p["rss_kb"] / 1024, 1),
                cpu_pct=p["cpu"],
                action="TERM",
                result=result,
                detail=f"stale_kill_{settings.SWEEP_STALE_KILL_HOURS}h,age={age_hours:.1f}h",
            ))
            log.info("sweep_stale_node_kill", pid=p["pid"], age_hours=round(age_hours, 1))
        elif p["etime_sec"] > warn_sec:
            actions.append(_make_action(
                priority="SWEEP-STALE-NODE",
                pid=p["pid"],
                process_name=p["command"][:80],
                mem_mb=round(p["rss_kb"] / 1024, 1),
                cpu_pct=p["cpu"],
                action="SKIP",
                result="warn",
                detail=f"stale_warn_{settings.SWEEP_STALE_WARN_HOURS}h,age={age_hours:.1f}h",
            ))
            log.warning("sweep_stale_node_warn", pid=p["pid"], age_hours=round(age_hours, 1))

    return actions


def _sweep_zombies() -> list[dict]:
    """Send SIGCHLD to parents of zombie processes."""
    actions = []

    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,stat="],
            capture_output=True, text=True, timeout=5,
        ).stdout

        parent_pids: set[int] = set()
        zombie_count = 0

        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2].startswith("Z"):
                zombie_count += 1
                parent_pids.add(int(parts[1]))

        for ppid in parent_pids:
            result = _safe_signal(ppid, signal.SIGCHLD)
            actions.append(_make_action(
                priority="SWEEP-ZOMBIE",
                pid=ppid,
                process_name=f"zombie-parent ({zombie_count} zombies)",
                mem_mb=0,
                cpu_pct=0,
                action="SIGCHLD",
                result=result,
            ))
            log.info("sweep_zombie_parent", ppid=ppid, zombie_count=zombie_count, result=result)

    except Exception:
        log.exception("sweep_zombies_error")

    return actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_etime(etime_str: str) -> int:
    s = etime_str.strip()

    m = re.match(r"(\d+)-(\d+):(\d+):(\d+)", s)
    if m:
        days, hours, mins, secs = (int(x) for x in m.groups())
        return days * 86400 + hours * 3600 + mins * 60 + secs

    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])

    return 0


def _get_process_details() -> list[dict]:
    output = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,rss=,%cpu=,etime=,command="],
        capture_output=True, text=True, timeout=5,
    ).stdout

    procs = []
    for line in output.splitlines():
        line = line.strip()
        if not line or "sweep" in line:
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            procs.append({
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "rss_kb": int(parts[2]),
                "cpu": float(parts[3]),
                "etime_sec": _parse_etime(parts[4]),
                "command": parts[5],
            })
        except (ValueError, IndexError):
            continue

    return procs


def _find_processes(pattern: str) -> list[dict]:
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,rss=,%cpu=,command="],
            capture_output=True, text=True, timeout=5,
        ).stdout

        procs = []
        for line in output.splitlines():
            if pattern in line and "grep" not in line and "sweep" not in line:
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


def _get_ppid(pid: int) -> int:
    try:
        output = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        ).stdout
        return int(output.strip())
    except Exception:
        return -1


def _safe_signal(pid: int, sig: int) -> str:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "already_dead"
    except PermissionError:
        return "no_permission"

    try:
        os.kill(pid, sig)
        return "success"
    except ProcessLookupError:
        return "already_dead"
    except PermissionError:
        return "no_permission"


def _make_action(
    *,
    priority: str,
    pid: int,
    process_name: str,
    mem_mb: float,
    cpu_pct: float,
    action: str,
    result: str,
    detail: str | None = None,
) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(UTC).isoformat(),
        "level": "SWEEP",
        "priority": priority,
        "pid": pid,
        "process_name": process_name,
        "mem_mb": mem_mb,
        "cpu_pct": cpu_pct,
        "action": action,
        "result": result,
        "detail": detail,
    }


def _save_actions(actions: list[dict]) -> None:
    """Schedule async save of sweep actions to database."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_save_actions(actions))
    except RuntimeError:
        log.warning("sweep_save_no_loop", count=len(actions))


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
                        a["cpu_pct"],
                        a["action"],
                        a["result"],
                        a.get("detail"),
                    )
                    for a in actions
                ],
            )
        log.info("sweep_actions_saved", count=len(actions))
    except Exception:
        log.exception("sweep_actions_save_error")
