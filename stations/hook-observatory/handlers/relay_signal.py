"""
tmux relay signal — Stop handler.

When Claude Code finishes a response, checks if a tmux-relay is waiting
for this pane's completion signal. If so, sends `tmux wait-for -S`.
Designed to be fast (<10ms) — no-op when no relay is pending.
"""

from __future__ import annotations

import os

from .base import ALLOW, HookResult, run_background


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    pane_id = os.environ.get("TMUX_PANE", "")
    if not pane_id:
        return ALLOW

    pane_safe = pane_id.replace("%", "")
    pending_file = f"/tmp/relay-pending-{pane_safe}.channel"

    if not os.path.isfile(pending_file):
        return ALLOW

    try:
        with open(pending_file) as f:
            channel = f.read().strip()
    except OSError:
        return ALLOW

    if channel:
        try:
            os.remove(pending_file)
        except OSError:
            pass
        run_background(["tmux", "wait-for", "-S", channel])

    return ALLOW
