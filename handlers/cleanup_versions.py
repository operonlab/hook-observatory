"""
Old Claude Code version cleanup — SessionStart handler.

Scans ~/.local/share/claude/versions/, keeps the current version
(symlink target of ~/.local/bin/claude), deletes the rest.
"""

from __future__ import annotations

import os

from .base import HOME, HookResult, message

VERSIONS_DIR = os.path.join(HOME, ".local", "share", "claude", "versions")
CLAUDE_BIN = os.path.join(HOME, ".local", "bin", "claude")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if not os.path.isdir(VERSIONS_DIR):
        return message("no versions directory found")

    try:
        current = os.path.realpath(CLAUDE_BIN)
    except OSError:
        current = ""

    removed = 0
    freed_parts: list[str] = []

    for name in os.listdir(VERSIONS_DIR):
        path = os.path.join(VERSIONS_DIR, name)
        if not os.path.isfile(path):
            continue
        if path == current:
            continue
        try:
            size = os.path.getsize(path)
            os.remove(path)
            removed += 1
            freed_parts.append(_human_size(size))
        except OSError:
            continue

    if removed > 0:
        freed = " ".join(freed_parts)
        return message(f"cleaned {removed} old versions (freed {freed})")
    return message("no old versions to clean")


def _human_size(nbytes: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if nbytes < 1024:
            return f"{nbytes:.0f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.0f}T"
