"""
Memory sync handler — PostToolUse for Edit/Write on auto-memory files.

Dual-purpose module:
  - Imported: provides handle() for hook registry (detects memory file writes)
  - Executed: python3 memory_sync.py <file_path> (background sync to memvault)

Implements the "dual-write" pattern: File (auto-memory) + Memvault (semantic search + KG).
"""

from __future__ import annotations

import os
import re
import sys

HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
PYTHON = os.path.join(HOME, ".local", "bin", "python3")

# auto-memory type → memvault block_type
TYPE_MAP = {
    "user": "general",
    "feedback": "attitude",
    "project": "knowledge",
    "reference": "knowledge",
}

# When imported as handler
if __name__ != "__main__":
    from .base import ALLOW, HookResult, run_background


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse handler: detect memory file writes and trigger background sync."""
    if tool_name not in ("Edit", "Write"):
        return ALLOW

    file_path = tool_input.get("file_path", "")
    if not file_path or not _is_memory_file(file_path):
        return ALLOW

    # Fire-and-forget: spawn self as worker
    run_background(
        [PYTHON, os.path.abspath(__file__), os.path.realpath(file_path)],
        cwd=os.path.join(HOME, "workshop"),
    )
    _log(f"triggered sync: {os.path.basename(file_path)}")
    return ALLOW


def _is_memory_file(path: str) -> bool:
    """Check if path is an auto-memory file (not the index)."""
    real = os.path.realpath(path)
    if not real.startswith(PROJECTS_DIR):
        return False
    if "/memory/" not in real:
        return False
    basename = os.path.basename(real)
    return basename.endswith(".md") and basename != "MEMORY.md"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from memory file."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content.strip()
    meta: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta, match.group(2).strip()


def _log(msg: str) -> None:
    print(f"[memory-sync] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Worker mode: python3 memory_sync.py <file_path>
# ---------------------------------------------------------------------------


def _worker(file_path: str) -> None:
    """Read memory file and sync to memvault via SDK client."""
    sys.path.insert(0, os.path.join(HOME, "workshop", "libs", "python", "src"))
    from sdk_client.memvault import MemvaultClient

    try:
        with open(file_path) as f:
            content = f.read()
    except Exception:
        return

    if not content.strip():
        return

    meta, body = _parse_frontmatter(content)
    mem_type = meta.get("type", "general")
    block_type = TYPE_MAP.get(mem_type, "general")

    basename = os.path.basename(file_path).replace(".md", "")
    tags = ["auto-memory", mem_type, basename]

    name = meta.get("name", basename)
    description = meta.get("description", "")
    extract_content = f"[{name}] {description}\n\n{body}" if description else body

    try:
        client = MemvaultClient()
        result = client.extract(
            content=extract_content,
            block_type=block_type,
            tags=tags,
        )
        _log(f"synced {basename} → memvault (id={result.get('id', '?')})")
    except Exception as e:
        _log(f"sync failed for {basename}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: memory_sync.py <file_path>", file=sys.stderr)
        sys.exit(1)
    _worker(sys.argv[1])
