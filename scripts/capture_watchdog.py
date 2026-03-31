#!/usr/bin/env /Users/joneshong/.local/bin/python3
"""Capture Haiku watchdog — standby if idle > 30 min.

Primary: Redis ``capture:haiku:last_used`` timestamp.
Fallback: file-based ``/tmp/capture_watchdog_ts`` when Redis unavailable.

Standby mode: idle → /exit only, don't restart.
Next request triggers lazy-start via llm_haiku._ensure_capture_window().
Designed to be called by Cronicle every 5 minutes.
"""

import subprocess
import sys
import time
from pathlib import Path

try:
    import redis as _redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

TMUX_TARGET = "capture"
IDLE_TIMEOUT = 1800  # 30 min
REDIS_KEY = "capture:haiku:last_used"
FALLBACK_TS_FILE = Path("/tmp/capture_watchdog_ts")


def tmux(*args: str) -> str:
    proc = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout.strip()


def is_claude_running() -> bool:
    """Check if Claude Code is the current command in capture pane."""
    cmd = tmux("display-message", "-t", TMUX_TARGET, "-p", "#{pane_current_command}")
    shells = {"zsh", "bash", "sh", "fish"}
    return cmd != "" and cmd.split("/")[-1] not in shells


def _redis_client():
    if not HAS_REDIS:
        return None
    try:
        r = _redis.Redis(decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _get_idle_secs(r) -> tuple[int | None, str]:
    """Return (idle_seconds, source_label) or (None, source_label).

    Uses the MOST RECENT timestamp from Redis and file fallback
    to avoid stale Redis values causing premature exit.
    """
    now = int(time.time())
    best_ts: int | None = None
    source = "none"

    if r:
        try:
            last_used = r.get(REDIS_KEY)
            if last_used is not None:
                ts = int(last_used)
                if best_ts is None or ts > best_ts:
                    best_ts = ts
                    source = "redis"
        except Exception:
            pass

    if FALLBACK_TS_FILE.exists():
        try:
            ts = int(FALLBACK_TS_FILE.read_text().strip())
            if best_ts is None or ts > best_ts:
                best_ts = ts
                source = "file-fallback"
        except (ValueError, OSError):
            pass

    if best_ts is not None:
        return now - best_ts, source
    return None, "none"


def _set_timestamp(r) -> None:
    now = str(int(time.time()))
    if r:
        try:
            r.set(REDIS_KEY, now)
        except Exception:
            pass
    FALLBACK_TS_FILE.write_text(now)


def standby() -> None:
    """Send /exit to put Claude in standby — don't restart."""
    print(f"[watchdog] standby: sending /exit (idle > {IDLE_TIMEOUT}s)")

    if is_claude_running():
        tmux("send-keys", "-t", TMUX_TARGET, "-l", "/exit")
        tmux("send-keys", "-t", TMUX_TARGET, "Enter")
        for _ in range(15):
            time.sleep(1)
            if not is_claude_running():
                break

    print("[watchdog] capture haiku now in standby (lazy-start on next request)")


def main() -> None:
    try:
        windows = tmux("list-windows", "-F", "#{window_name}")
    except Exception:
        print("[watchdog] tmux not available", file=sys.stderr)
        return

    if TMUX_TARGET not in windows.split("\n"):
        print(f"[watchdog] no '{TMUX_TARGET}' window found — skipping")
        return

    r = _redis_client()

    if not is_claude_running():
        print("[watchdog] Claude not running in capture — already in standby")
        return

    idle_secs, source = _get_idle_secs(r)

    if idle_secs is None:
        _set_timestamp(r)
        print("[watchdog] initialized timestamp")
        return

    print(f"[watchdog] idle: {idle_secs}s / {IDLE_TIMEOUT}s threshold ({source})")

    if idle_secs >= IDLE_TIMEOUT:
        standby()
    else:
        print("[watchdog] still fresh — no action")


if __name__ == "__main__":
    main()
