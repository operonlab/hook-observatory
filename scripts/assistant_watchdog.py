#!/usr/bin/env /Users/joneshong/.local/bin/python3
"""Assistant Haiku watchdog — standby if idle > 30 min.

Same pattern as capture_watchdog.py.
Primary: Redis ``assistant:haiku:last_used`` timestamp.
Fallback: file-based ``/tmp/assistant_watchdog_ts``.

Standby: /exit only, don't restart.
Next request triggers lazy-start via services._ensure_assistant_window().
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

TMUX_TARGET = "assistant"
IDLE_TIMEOUT = 1800  # 30 min
REDIS_KEY = "assistant:haiku:last_used"
FALLBACK_TS_FILE = Path("/tmp/assistant_watchdog_ts")


def tmux(*args: str) -> str:
    proc = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout.strip()


def is_claude_running() -> bool:
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
    if r:
        try:
            last_used = r.get(REDIS_KEY)
            if last_used is not None:
                return int(time.time()) - int(last_used), "redis"
        except Exception:
            pass

    if FALLBACK_TS_FILE.exists():
        try:
            ts = int(FALLBACK_TS_FILE.read_text().strip())
            return int(time.time()) - ts, "file-fallback"
        except (ValueError, OSError):
            pass

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
    print(f"[assistant-watchdog] standby: sending /exit (idle > {IDLE_TIMEOUT}s)")

    if is_claude_running():
        tmux("send-keys", "-t", TMUX_TARGET, "-l", "/exit")
        tmux("send-keys", "-t", TMUX_TARGET, "Enter")
        for _ in range(15):
            time.sleep(1)
            if not is_claude_running():
                break

    print("[assistant-watchdog] now in standby (lazy-start on next request)")


def main() -> None:
    try:
        windows = tmux("list-windows", "-F", "#{window_name}")
    except Exception:
        print("[assistant-watchdog] tmux not available", file=sys.stderr)
        return

    if TMUX_TARGET not in windows.split("\n"):
        print(f"[assistant-watchdog] no '{TMUX_TARGET}' window — skipping")
        return

    r = _redis_client()

    if not is_claude_running():
        print("[assistant-watchdog] Claude not running — already in standby")
        return

    idle_secs, source = _get_idle_secs(r)

    if idle_secs is None:
        _set_timestamp(r)
        print("[assistant-watchdog] initialized timestamp")
        return

    print(f"[assistant-watchdog] idle: {idle_secs}s / {IDLE_TIMEOUT}s ({source})")

    if idle_secs >= IDLE_TIMEOUT:
        standby()
    else:
        print("[assistant-watchdog] still fresh — no action")


if __name__ == "__main__":
    main()
