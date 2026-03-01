"""
Commit verification gate — PreToolUse handler for Bash.

Gates `git commit` and `gh pr create` with a /tmp/.claude-verified marker file.
Workflow: run tests → touch marker → commit succeeds.
"""

from __future__ import annotations

import os
import re

from .base import ALLOW, HookResult, approve, block

MARKER = "/tmp/.claude-verified"

_COMMIT_RE = re.compile(r"(git commit|gh pr create)")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name != "Bash":
        return ALLOW

    command = tool_input.get("command", "")
    if not _COMMIT_RE.search(command):
        return ALLOW

    # Marker exists → approve and consume it
    if os.path.isfile(MARKER):
        try:
            os.remove(MARKER)
        except OSError:
            pass
        return approve()

    # No marker → block with instructions
    return block(
        "⚠️ VERIFICATION GATE: commit/PR 前必須先驗證。\n"
        "1. 執行測試、build、lint 等驗證命令\n"
        "2. 確認全部通過\n"
        "3. 執行: touch /tmp/.claude-verified\n"
        "4. 重新嘗試 commit"
    )
