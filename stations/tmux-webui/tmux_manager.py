"""tmux operations wrapper for tmux-webui V2."""

import asyncio
import json
import logging
import os

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
    rc, out, _ = await _run([
        "tmux", "list-sessions", "-F",
        "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}",
    ])
    if rc != 0:
        return []
    sessions = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            sessions.append({
                "name": parts[0],
                "windows": int(parts[1]),
                "attached": int(parts[2]),
            })
    return sessions


async def list_windows(session: str) -> list[dict]:
    rc, out, _ = await _run([
        "tmux", "list-windows", "-t", session, "-F",
        "#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}",
    ])
    if rc != 0:
        return []
    windows = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            windows.append({
                "index": int(parts[0]),
                "name": parts[1],
                "active": int(parts[2]),
                "panes": int(parts[3]),
            })
    return windows


async def list_panes(session: str) -> list[dict]:
    rc, out, _ = await _run([
        "tmux", "list-panes", "-s", "-t", session, "-F",
        "#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_active}"
        "\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_title}",
    ])
    if rc != 0:
        return []
    panes = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 7:
            panes.append({
                "window": int(parts[0]),
                "window_name": parts[1],
                "pane": int(parts[2]),
                "active": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
                "command": parts[6],
                "title": parts[7] if len(parts) > 7 else "",
                "id": f"{parts[0]}.{parts[2]}",
            })
    return panes


# ── Pane capture / send-keys ──


async def capture_pane(target: str, lines: int = 150) -> str:
    rc, out, _ = await _run([
        "tmux", "capture-pane", "-t", target, "-p", "-e", "-S", f"-{lines}",
    ])
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
    rc, _, stderr = await _run([
        "tmux", "resize-pane", "-t", target, "-x", str(cols), "-y", str(rows),
    ])
    if rc != 0:
        logger.warning("resize-pane failed for %s: %s", target, stderr.strip())
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
    """Collect system metrics from tmux status scripts + LLM usage."""
    scripts = {
        "net": "net-speed", "cpu": "cpu-status",
        "mem": "mem-status", "disk": "disk-status",
    }
    results = {}

    for key, script in scripts.items():
        try:
            script_path = os.path.expanduser(f"~/.tmux/scripts/{script}.sh")
            if not os.path.exists(script_path):
                results[key] = ""
                continue
            rc, out, _ = await _run([script_path])
            results[key] = out.strip() if rc == 0 else ""
        except Exception:
            results[key] = ""

    # LLM Usage
    llm_keys = {
        "claude_5h": "llm_cc_5h", "claude_7d": "llm_cc_7d", "claude_ex": "llm_cc_ex",
        "codex_5h": "llm_cx_5h", "codex_7d": "llm_cx_7d",
        "gemini_pro": "llm_gm_pro",
    }
    for k in llm_keys:
        results[k] = "?"

    # Try sysmon fallback file first
    sysmon_file = "/tmp/pulso-sysmon-latest.json"
    llm_found = False
    try:
        if os.path.exists(sysmon_file):
            with open(sysmon_file) as f:
                sysmon_data = json.load(f)
            for result_key, sysmon_key in llm_keys.items():
                val = sysmon_data.get(sysmon_key, "?")
                if val and val != "?":
                    results[result_key] = val
                    llm_found = True
    except Exception:
        pass

    # Fallback: quota-all.sh
    if not llm_found:
        quota_script = os.path.expanduser("~/.tmux/scripts/quota-all.sh")
        metric_map = {
            "claude_5h": "cc-5h", "claude_7d": "cc-7d", "claude_ex": "cc-ex",
            "codex_5h": "cx-5h", "codex_7d": "cx-7d",
            "gemini_pro": "gm-pro",
        }
        for result_key, script_arg in metric_map.items():
            try:
                if not os.path.exists(quota_script):
                    break
                rc, out, _ = await _run([quota_script, script_arg])
                val = out.strip() if rc == 0 else "?"
                if val:
                    results[result_key] = val
            except Exception:
                pass

    return results
