"""tmux operations wrapper for tmux-webui V2."""

import asyncio
import json
import logging

logger = logging.getLogger("tmux-webui")


async def _run(args: list[str]) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


# ── Session / Window / Pane queries ──


async def list_sessions() -> list[dict]:
    rc, out, _ = await _run(
        [
            "tmux",
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}",
        ]
    )
    if rc != 0:
        return []
    sessions = []
    for line in out.strip().splitlines():
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
    rc, out, _ = await _run(
        [
            "tmux",
            "list-windows",
            "-t",
            session,
            "-F",
            "#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}",
        ]
    )
    if rc != 0:
        return []
    windows = []
    for line in out.strip().splitlines():
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
    rc, out, _ = await _run(
        [
            "tmux",
            "list-panes",
            "-s",
            "-t",
            session,
            "-F",
            "#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_active}"
            "\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_title}",
        ]
    )
    if rc != 0:
        return []
    panes = []
    for line in out.strip().splitlines():
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
                    "id": f"{parts[0]}.{parts[2]}",
                }
            )
    return panes


# ── Pane capture / send-keys ──


async def capture_pane(target: str, lines: int = 150) -> str:
    rc, out, _ = await _run(  # noqa: RUF059
        [
            "tmux",
            "capture-pane",
            "-t",
            target,
            "-p",
            "-e",
            "-S",
            f"-{lines}",
        ]
    )
    return out


async def send_keys(target: str, text: str, literal: bool = True) -> bool:
    args = ["tmux", "send-keys", "-t", target]
    if literal:
        args += ["-l", text]
    else:
        args.append(text)
    rc, _, stderr = await _run(args)
    if rc != 0:
        logger.warning("send-keys failed for %s: %s", target, stderr.strip())
    return rc == 0


# ── Window management ──


async def new_window(session: str) -> bool:
    rc, _, _ = await _run(["tmux", "new-window", "-t", session])
    return rc == 0


async def kill_window(session: str, window: int) -> bool:
    rc, _, _ = await _run(["tmux", "kill-window", "-t", f"{session}:{window}"])
    return rc == 0


async def resize_pane(target: str, cols: int, rows: int) -> bool:
    """Resize a tmux pane to the given cols x rows."""
    rc, _, stderr = await _run(
        [
            "tmux",
            "resize-pane",
            "-t",
            target,
            "-x",
            str(cols),
            "-y",
            str(rows),
        ]
    )
    if rc != 0:
        logger.warning("resize-pane failed for %s: %s", target, stderr.strip())
    return rc == 0


async def select_layout(target: str, layout: str = "even-horizontal") -> bool:
    """Apply a tmux layout preset to a window. e.g. even-horizontal, even-vertical, tiled."""
    rc, _, stderr = await _run(["tmux", "select-layout", "-t", target, layout])
    if rc != 0:
        logger.warning("select-layout failed for %s: %s", target, stderr.strip())
    return rc == 0


async def select_pane(session: str, direction: str) -> bool:
    """Select pane by direction: -L, -R, -U, -D."""
    flag_map = {"left": "-L", "right": "-R", "up": "-U", "down": "-D"}
    flag = flag_map.get(direction.lower())
    if not flag:
        return False
    rc, _, _ = await _run(["tmux", "select-pane", "-t", session, flag])
    return rc == 0


# ── System metrics ──


async def status_metrics() -> dict:
    """Collect system metrics + LLM usage from agent-metrics sysmon API."""
    results = {"net": "", "cpu": "", "mem": "", "disk": "", "llm": {}}

    try:
        rc, out, _ = await _run(
            ["curl", "-sf", "--max-time", "3", "http://127.0.0.1:8795/sysmon/current"]
        )
        if rc != 0 or not out.strip():
            return results

        data = json.loads(out)

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
