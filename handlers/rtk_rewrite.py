"""RTK (Rust Token Killer) command rewrite handler.

Rewrites Bash commands to their rtk equivalent for token savings.
Delegates all rewrite logic to `rtk rewrite` binary (Rust, <10ms).

Runs AFTER bash_safety in the PreToolUse registry — if safety blocks,
the block wins regardless (dispatcher merges decisions: block > all).
"""

from __future__ import annotations

from .base import ALLOW, HookResult, find_executable, run_cmd


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name != "Bash":
        return ALLOW

    cmd = tool_input.get("command", "")
    if not cmd or cmd.startswith("rtk "):
        return ALLOW

    rtk_bin = find_executable("rtk")
    if not rtk_bin:
        return ALLOW

    result = run_cmd([rtk_bin, "rewrite", cmd], timeout=3)
    if result is None or result.returncode != 0:
        return ALLOW

    rewritten = result.stdout.strip()
    if not rewritten or rewritten == cmd:
        return ALLOW

    return HookResult(updated_input={"command": rewritten})
