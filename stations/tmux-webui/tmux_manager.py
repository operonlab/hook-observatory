"""tmux operations wrapper for tmux-webui V2."""

import asyncio
import json
import logging

from tmux_lib.primitives import capture_async, send_text_async, tmux_run_async

logger = logging.getLogger("tmux-webui")


# ── Session / Window / Pane queries ──


async def list_sessions() -> list[dict]:
    r = await tmux_run_async(
        "list-sessions",
        "-F",
        "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}",
    )
    if not r.ok:
        return []
    sessions = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            sessions.append(
                {
                    "name": parts[0],
                    "windows": int(parts[1]),
                    "attached": int(parts[2]),
                }
            )
    return sessions


async def list_windows(session: str) -> list[dict]:
    r = await tmux_run_async(
        "list-windows",
        "-t",
        session,
        "-F",
        "#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}",
    )
    if not r.ok:
        return []
    windows = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            windows.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "active": int(parts[2]),
                    "panes": int(parts[3]),
                }
            )
    return windows


async def list_panes(session: str) -> list[dict]:
    r = await tmux_run_async(
        "list-panes",
        "-s",
        "-t",
        session,
        "-F",
        "#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_active}"
        "\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_title}\t#{alternate_on}",
    )
    if not r.ok:
        return []
    panes = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 7:
            panes.append(
                {
                    "window": int(parts[0]),
                    "window_name": parts[1],
                    "pane": int(parts[2]),
                    "active": int(parts[3]),
                    "width": int(parts[4]),
                    "height": int(parts[5]),
                    "command": parts[6],
                    "title": parts[7] if len(parts) > 7 else "",
                    "alternate_on": int(parts[8]) if len(parts) > 8 else 0,
                    "id": f"{parts[0]}.{parts[2]}",
                }
            )
    return panes


# ── Pane capture / send-keys ──


async def capture_pane(target: str, lines: int = 150) -> str:
    out = await capture_async(target, start_line=-lines, escape_sequences=True)
    return out or ""


async def capture_pane_visible(target: str) -> str:
    """Capture only visible content (no scrollback).

    Use for alt-screen panes to get pure TUI content without
    main buffer scrollback bleeding through.
    """
    out = await capture_async(target, start_line=0, escape_sequences=True)
    return out or ""


async def capture_pane_scrollback(target: str, lines: int = 5000) -> str:
    """Capture extended scrollback from main buffer.

    When pane is in alt screen, this returns the main buffer history
    (content from before the TUI app started).
    """
    out = await capture_async(target, start_line=-lines, escape_sequences=True)
    return out or ""


async def send_keys(target: str, text: str, literal: bool = True) -> bool:
    """Send text to a tmux pane."""
    try:
        await send_text_async(target, text, literal=literal, buf_name="_webui_paste")
        return True
    except RuntimeError:
        logger.warning("send-keys failed for %s", target)
        return False


# ── Window management ──


async def new_window(session: str) -> bool:
    r = await tmux_run_async("new-window", "-t", session)
    return r.ok


async def kill_window(session: str, window: int) -> bool:
    r = await tmux_run_async("kill-window", "-t", f"{session}:{window}")
    return r.ok


async def resize_pane(target: str, cols: int, rows: int) -> bool:
    """Resize a tmux pane to the given cols x rows."""
    r = await tmux_run_async(
        "resize-pane",
        "-t",
        target,
        "-x",
        str(cols),
        "-y",
        str(rows),
    )
    if not r.ok:
        logger.warning("resize-pane failed for %s: %s", target, r.stderr)
    return r.ok


async def select_layout(target: str, layout: str = "even-horizontal") -> bool:
    """Apply a tmux layout preset to a window."""
    r = await tmux_run_async("select-layout", "-t", target, layout)
    if not r.ok:
        logger.warning("select-layout failed for %s: %s", target, r.stderr)
    return r.ok


async def select_pane(session: str, direction: str) -> bool:
    """Select pane by direction: -L, -R, -U, -D."""
    flag_map = {"left": "-L", "right": "-R", "up": "-U", "down": "-D"}
    flag = flag_map.get(direction.lower())
    if not flag:
        return False
    r = await tmux_run_async("select-pane", "-t", session, flag)
    return r.ok


# ── System metrics ──


async def status_metrics() -> dict:
    """Collect system metrics + LLM usage from agent-metrics sysmon API."""
    results = {"net": "", "cpu": "", "mem": "", "disk": "", "llm": {}}

    try:
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-sf",
            "--max-time",
            "3",
            "http://127.0.0.1:10103/sysmon/current",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0 or not stdout_b:
            return results

        data = json.loads(stdout_b.decode("utf-8", errors="replace"))

        # System metrics — use pre-formatted display strings from agent-metrics
        results["net"] = data.get("net_display", "")
        results["cpu"] = data.get("cpu_display", "")
        results["mem"] = data.get("mem_display", "")
        results["disk"] = data.get("disk_display", "")

        # LLM Usage — group by provider: {cc: {5h: "26%", ...}, gm: {pro: "11%", flash: "9%"}}
        llm: dict[str, dict[str, str]] = {}
        for k, v in data.items():
            if not k.startswith("llm_") or k == "llm_display":
                continue
            if not v or v == "?":
                continue
            rest = k[4:]  # "cc_5h"
            sep = rest.find("_")
            if sep < 0:
                continue
            provider, metric = rest[:sep], rest[sep + 1 :]
            llm.setdefault(provider, {})[metric] = v
        results["llm"] = llm
    except Exception:  # noqa: S110
        pass

    return results
