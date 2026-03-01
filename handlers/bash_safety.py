"""
Bash command safety checker — PreToolUse handler for Bash tool.

Layer 2 defense (after permissions.deny). Fires for sub-agents too.
Uses regex for robust pattern matching immune to flag reordering bypasses.
"""

from __future__ import annotations

import os
import re

from .base import ALLOW, HookResult, block


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name != "Bash":
        return ALLOW
    command = tool_input.get("command", "")
    if not command:
        return ALLOW
    reason = _check_command(command)
    return block(f"Safety hook: {reason}") if reason else ALLOW


# ---------------------------------------------------------------------------
# Core checking logic
# ---------------------------------------------------------------------------

def _check_command(full_cmd: str) -> str | None:
    """Check a full command (may contain chains/pipes/subshells)."""
    for segment in _split_commands(full_cmd):
        reason = _check_segment(segment)
        if reason:
            return reason

    for sub_cmd in re.findall(r"\$\(([^)]+)\)", full_cmd):
        for segment in _split_commands(sub_cmd):
            reason = _check_segment(segment)
            if reason:
                return f"{reason} (in subshell)"

    for sub_cmd in re.findall(r"`([^`]+)`", full_cmd):
        for segment in _split_commands(sub_cmd):
            reason = _check_segment(segment)
            if reason:
                return f"{reason} (in subshell)"

    return None


_HOME = os.path.expanduser("~")

def _check_segment(cmd: str) -> str | None:
    """Check a single command segment against deny patterns."""
    cmd = cmd.strip()
    if not cmd:
        return None

    # rm: recursive + force + critical target
    rm_match = re.search(r"\brm\b(.*)", cmd)
    if rm_match:
        args = rm_match.group(1)
        short_flags = "".join(re.findall(r"(?:^|\s)-([a-zA-Z]+)", args))
        long_flags = re.findall(r"--(\w[\w-]*)", args)
        has_r = "r" in short_flags or "R" in short_flags or "recursive" in long_flags
        has_f = "f" in short_flags or "force" in long_flags

        if has_r and has_f:
            tokens = args.split()
            targets = [t.strip("'\"") for t in tokens if not t.startswith("-")]
            for t in targets:
                expanded = os.path.expanduser(t)
                if t in ("/", "*", ".", "..", "/*", "~/*"):
                    return f"rm recursive+force on critical path: {t}"
                if expanded.rstrip("/") == _HOME:
                    return "rm recursive+force on home directory"
                if expanded.rstrip("/") == os.path.join(_HOME, "workshop"):
                    return "rm recursive+force on workshop directory"
                if expanded.startswith(_HOME + "/"):
                    rel = expanded[len(_HOME) + 1:].rstrip("/")
                    if "/" not in rel:
                        return f"rm recursive+force on home-level directory: ~/{rel}"

    if re.search(r"\bsudo\b", cmd):
        return "sudo (privilege escalation)"
    if re.search(r"\bmkfs\b", cmd):
        return "mkfs (format disk)"
    if re.search(r"\bfdisk\b", cmd):
        return "fdisk (partition disk)"
    if re.search(r"\bdd\b.*\bif=/dev/(zero|urandom|random)\b", cmd):
        return "dd from /dev/zero or urandom"
    if re.search(r"\bdd\b.*\bof=/dev/", cmd):
        return "dd writing to device"
    if re.search(r"\bchmod\b.*\b777\b", cmd):
        return "chmod 777"
    if re.search(r"\bgit\s+push\b", cmd):
        if re.search(r"--force(?!-with-lease)\b", cmd) or re.search(r"(?:^|\s)-[a-zA-Z]*f", cmd):
            return "git force push"
    if re.search(r"\bgit\s+reset\b.*--hard\b", cmd):
        return "git reset --hard"
    if re.search(r"\bgit\s+clean\b.*-[a-zA-Z]*f", cmd):
        return "git clean with force"
    if re.search(r"\bnpm\s+publish\b", cmd):
        return "npm publish"
    if re.search(r"\byarn\s+publish\b", cmd):
        return "yarn publish"
    if re.search(r"\bdocker\s+run\b.*--privileged\b", cmd):
        return "docker run --privileged"
    if re.search(r"\bgh\s+repo\s+delete\b", cmd):
        return "gh repo delete"

    return None


def _split_commands(cmd: str) -> list[str]:
    """Split on ;, &&, ||, | while respecting quotes."""
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0

    while i < len(cmd):
        c = cmd[i]
        if escaped:
            current.append(c)
            escaped = False
            i += 1
            continue
        if c == "\\":
            escaped = True
            current.append(c)
            i += 1
            continue
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
        elif not in_single and not in_double:
            if c == ";":
                segments.append("".join(current))
                current = []
            elif c == "&" and i + 1 < len(cmd) and cmd[i + 1] == "&":
                segments.append("".join(current))
                current = []
                i += 1
            elif c == "|" and i + 1 < len(cmd) and cmd[i + 1] == "|":
                segments.append("".join(current))
                current = []
                i += 1
            elif c == "|":
                segments.append("".join(current))
                current = []
            else:
                current.append(c)
        else:
            current.append(c)
        i += 1

    if current:
        segments.append("".join(current))
    return segments
