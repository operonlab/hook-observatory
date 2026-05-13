"""
Review Gate — Stop hook handler.
Cannibalized from: openai/codex-plugin-cc (Stop Review Gate pattern)

On Stop event:
  - Check if there are uncommitted code changes in the working tree
  - If review gate enabled: BLOCK if code changes found without review
  - If disabled (default): just emit informational message

Config: ~/.claude/data/review-gate.json
  {"enabled": false}  — default, message-only
  {"enabled": true}   — block mode (requires explicit opt-in)

Enable/disable via: python3 ~/.claude/data/review-gate-ctl.py --enable / --disable
"""

from __future__ import annotations

import json
import os

from .base import ALLOW, HookResult, block, message, run_cmd

CONFIG_PATH = os.path.expanduser("~/.claude/data/review-gate.json")

# File extensions considered "code" (changes to these trigger the gate)
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
}

# Paths to ignore even if they have code extensions
IGNORE_PATTERNS = {
    "test",
    "tests",
    "__pycache__",
    "node_modules",
    ".worktrees",
    "dist",
    "build",
    ".git",
}


def _load_config() -> dict:
    """Load review gate config. Returns defaults if missing."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": False}


def _has_code_changes(cwd: str | None = None) -> tuple[bool, list[str]]:
    """Check for uncommitted code file changes. Returns (has_changes, changed_files)."""
    result = run_cmd(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
        timeout=5,
        cwd=cwd,
    )
    if result is None or result.returncode != 0:
        # Also check unstaged + untracked
        result = run_cmd(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            timeout=5,
            cwd=cwd,
        )
        if result is None or not result.stdout.strip():
            return False, []
        # Parse porcelain output: first 3 chars are status, rest is filename
        files = []
        for line in result.stdout.strip().splitlines():
            if len(line) > 3:
                fname = line[3:].strip().split(" -> ")[-1]  # handle renames
                files.append(fname)
        return _filter_code_files(files)

    files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    return _filter_code_files(files)


def _filter_code_files(files: list[str]) -> tuple[bool, list[str]]:
    """Filter to only code files, excluding test/build directories."""
    code_files = []
    for f in files:
        # Check extension
        _, ext = os.path.splitext(f)
        if ext not in CODE_EXTENSIONS:
            continue
        # Check ignored patterns
        parts = f.replace("\\", "/").split("/")
        if any(p in IGNORE_PATTERNS for p in parts):
            continue
        code_files.append(f)
    return bool(code_files), code_files


def handle(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    """Stop hook: review gate check."""
    if event_type != "Stop":
        return ALLOW

    # Determine working directory
    cwd = None
    try:
        parsed = json.loads(raw_input) if raw_input.strip() else {}
        cwd = parsed.get("cwd")
    except (json.JSONDecodeError, AttributeError):
        pass

    has_changes, changed_files = _has_code_changes(cwd)
    if not has_changes:
        return ALLOW

    config = _load_config()
    file_summary = ", ".join(changed_files[:5])
    if len(changed_files) > 5:
        file_summary += f" (+{len(changed_files) - 5} more)"

    if config.get("enabled"):
        # Block mode: prevent session end until changes are reviewed/committed
        return block(
            f"Review gate: {len(changed_files)} uncommitted code change(s) detected "
            f"({file_summary}). Review or commit before ending session."
        )

    # Message-only mode (default): inform but don't block
    return message(f"⚠ {len(changed_files)} uncommitted code change(s): {file_summary}")
