"""
Auto-format handler — PostToolUse handler for Edit/Write.

Runs ruff (Python) or biome (TS/JS) after file modifications.
Formatting must never block the agent — all errors are swallowed.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .base import ALLOW, HookResult

RUFF_BIN = "/opt/homebrew/bin/ruff"
PY_EXTS = {".py"}
JS_EXTS = {".ts", ".tsx", ".js", ".jsx"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".worktrees"}


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name not in ("Edit", "Write"):
        return ALLOW

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return ALLOW

    file_path = os.path.realpath(file_path)
    if not os.path.isfile(file_path):
        return ALLOW
    if _in_skip_dir(file_path):
        return ALLOW
    if not _find_git_root(file_path):
        return ALLOW

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in PY_EXTS:
        _format_python(file_path)
    elif ext in JS_EXTS:
        _format_js(file_path)

    return ALLOW


def _log(msg: str) -> None:
    print(f"[auto-format] {msg}", file=sys.stderr)


def _find_git_root(path: str) -> str | None:
    current = os.path.dirname(path) if os.path.isfile(path) else path
    while current != "/":
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return None


def _in_skip_dir(file_path: str) -> bool:
    return any(p in SKIP_DIRS for p in file_path.split(os.sep))


def _find_biome_config(file_path: str) -> str | None:
    current = os.path.dirname(file_path)
    while current != "/":
        for name in ("biome.json", "biome.jsonc"):
            if os.path.isfile(os.path.join(current, name)):
                return current
        current = os.path.dirname(current)
    return None


def _find_biome_bin(config_dir: str) -> str | None:
    local_bin = os.path.join(config_dir, "node_modules", ".bin", "biome")
    if os.path.isfile(local_bin):
        return local_bin
    try:
        subprocess.run(["biome", "--version"], capture_output=True, timeout=5)
        return "biome"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _format_python(file_path: str) -> None:
    if not os.path.isfile(RUFF_BIN):
        return
    try:
        subprocess.run([RUFF_BIN, "check", "--fix", "--silent", file_path],
                       capture_output=True, text=True, timeout=15)
        result = subprocess.run([RUFF_BIN, "format", "--quiet", file_path],
                                capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            _log(f"ruff OK: {file_path}")
        else:
            _log(f"ruff error: {result.stderr.strip()}")
    except Exception as e:
        _log(f"ruff exception: {e}")


def _format_js(file_path: str) -> None:
    config_dir = _find_biome_config(file_path)
    if not config_dir:
        return
    biome_bin = _find_biome_bin(config_dir)
    if not biome_bin:
        return
    try:
        result = subprocess.run(
            [biome_bin, "check", "--write", "--no-errors-on-unmatched", file_path],
            capture_output=True, text=True, timeout=15, cwd=config_dir,
        )
        if result.returncode == 0:
            _log(f"biome OK: {file_path}")
        else:
            _log(f"biome error: {result.stderr.strip()}")
    except Exception as e:
        _log(f"biome exception: {e}")
