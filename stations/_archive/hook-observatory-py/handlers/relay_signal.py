"""
tmux relay signal — Stop handler.

When Claude Code finishes a response, checks if a tmux-relay is waiting
for this pane's completion signal. If so, sends `tmux wait-for -S`.
Also updates Redis cache with pane status and pre-caches result.
Designed to be fast (<10ms) — no-op when no relay is pending.
"""

from __future__ import annotations

import json
import os
import time

from .base import ALLOW, HookResult, run_background

# Lazy Redis connection — only initialized when needed
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.from_url(
                os.getenv("WORKSHOP_REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
        except Exception:
            return None
    return _redis_client


def _update_redis_cache(pane_safe: str) -> None:
    """Update Redis cache: mark pane idle + pre-cache result."""
    r = _get_redis()
    if not r:
        return

    try:
        raw = r.hget("relay:panes", pane_safe)
        signal_file = ""
        if raw:
            data = json.loads(raw)
            signal_file = data.get("signal_file", "")
            data["status"] = "idle"
            data["updated_at"] = time.time()
            r.hset("relay:panes", pane_safe, json.dumps(data))

        # Pre-cache result
        if signal_file:
            basename = os.path.basename(signal_file)
            r.set(
                f"relay:result:{basename}",
                json.dumps(
                    {
                        "status": "success",
                        "completed_at": time.time(),
                        "pane": f"%{pane_safe}",
                    }
                ),
                ex=3600,
            )

        r.set("relay:cache_ts", str(time.time()), ex=60)
    except Exception:
        pass  # Cache is advisory — never block the hook


def _debug_log(msg: str) -> None:
    """Append debug line to relay signal log (advisory, never fails)."""
    try:
        with open("/tmp/relay-signal-debug.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    pane_id = os.environ.get("TMUX_PANE", "")
    if not pane_id:
        return ALLOW

    pane_safe = pane_id.replace("%", "")
    pending_file = f"/tmp/relay-pending-{pane_safe}.channel"

    if not os.path.isfile(pending_file):
        _debug_log(f"no-op pane={pane_safe} (no pending file)")
        return ALLOW

    try:
        with open(pending_file) as f:
            channel = f.read().strip()
    except OSError:
        _debug_log(f"error pane={pane_safe} (cannot read pending file)")
        return ALLOW

    if channel:
        try:
            os.remove(pending_file)
        except OSError:
            pass
        run_background(["tmux", "wait-for", "-S", channel])
        _debug_log(f"signaled pane={pane_safe} channel={channel}")

        # Update Redis cache (advisory, non-blocking)
        _update_redis_cache(pane_safe)

    return ALLOW
