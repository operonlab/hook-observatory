"""
Context injection — SubagentStart handler.

Phase-specific context injection inspired by Trellis JSONL manifests.

Resolution order:
  1. `.context/{agent_type}.jsonl` (agent-specific override)
  2. `.context/default.jsonl` (project-wide override)
  3. Auto-detect from project structure (zero-config)

Auto-detect scans for:
  - CLAUDE.md (project instructions — only if not at ~/.claude/)
  - spec/ or docs/ directories (.md files)
  - .claude/rules/ (.md files)

JSONL format (one entry per line):
  {"file": "spec/api-design.md", "reason": "API contract"}
  {"file": "src/models/", "reason": "Data models", "type": "directory"}

When type="directory", all .md files in that directory are included.
"""

from __future__ import annotations

import json
import os

from .base import ALLOW, HookResult, run_cmd

_MAX_INJECT_SIZE = 8000  # chars — guard against bloating context


def _find_context_dir(cwd: str) -> str | None:
    """Find .context/ directory in cwd or git root."""
    candidate = os.path.join(cwd, ".context")
    if os.path.isdir(candidate):
        return candidate

    result = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=5)
    if result and result.returncode == 0:
        git_root = result.stdout.strip()
        if git_root != cwd:
            candidate = os.path.join(git_root, ".context")
            if os.path.isdir(candidate):
                return candidate

    return None


def _read_jsonl(path: str) -> list[dict]:
    """Read a JSONL file, return list of parsed entries."""
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return entries


def _read_file_content(path: str, base_dir: str) -> str:
    """Read a file relative to base_dir, return content or empty."""
    full_path = os.path.join(base_dir, path) if not os.path.isabs(path) else path
    try:
        with open(full_path) as f:
            return f.read()
    except OSError:
        return ""


def _read_directory_md(path: str, base_dir: str) -> str:
    """Read all .md files in a directory."""
    full_path = os.path.join(base_dir, path) if not os.path.isabs(path) else path
    parts = []
    try:
        for name in sorted(os.listdir(full_path)):
            if name.endswith(".md"):
                fp = os.path.join(full_path, name)
                try:
                    with open(fp) as f:
                        parts.append(f"### {name}\n{f.read()}")
                except OSError:
                    continue
    except OSError:
        pass
    return "\n\n".join(parts)


def _build_context(entries: list[dict], base_dir: str) -> str:
    """Build injected context string from JSONL entries."""
    sections = []
    total_size = 0

    for entry in entries:
        file_path = entry.get("file", "")
        reason = entry.get("reason", "")
        entry_type = entry.get("type", "file")

        if not file_path:
            continue

        if entry_type == "directory":
            content = _read_directory_md(file_path, base_dir)
        else:
            content = _read_file_content(file_path, base_dir)

        if not content:
            continue

        section = f"## {reason or file_path}\n{content}"
        if total_size + len(section) > _MAX_INJECT_SIZE:
            sections.append(f"... (context truncated at {_MAX_INJECT_SIZE} chars)")
            break
        sections.append(section)
        total_size += len(section)

    return "\n\n".join(sections)


def _find_project_root(cwd: str) -> str:
    """Find git root or return cwd."""
    result = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=5)
    if result and result.returncode == 0:
        return result.stdout.strip()
    return cwd


def _auto_detect_entries(root: str) -> list[dict]:
    """Auto-detect context entries from project structure."""
    entries = []

    # Project-level CLAUDE.md (skip ~/.claude/CLAUDE.md — that's global)
    claude_md = os.path.join(root, "CLAUDE.md")
    home_claude = os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
    if os.path.isfile(claude_md) and os.path.realpath(claude_md) != os.path.realpath(home_claude):
        entries.append({"file": "CLAUDE.md", "reason": "Project instructions"})

    # spec/ or docs/ directories
    for dirname, reason in [("spec", "Specifications"), ("docs", "Documentation")]:
        dirpath = os.path.join(root, dirname)
        if os.path.isdir(dirpath):
            # Only include if it has .md files
            has_md = any(f.endswith(".md") for f in os.listdir(dirpath))
            if has_md:
                entries.append({"file": dirname, "reason": reason, "type": "directory"})

    # .claude/rules/ (project-specific rules, not global ~/.claude/rules/)
    rules_dir = os.path.join(root, ".claude", "rules")
    if os.path.isdir(rules_dir):
        has_md = any(f.endswith(".md") for f in os.listdir(rules_dir))
        if has_md:
            entries.append(
                {"file": ".claude/rules", "reason": "Project rules", "type": "directory"}
            )

    return entries


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if event_type != "SubagentStart":
        return ALLOW

    # Parse event data
    try:
        data = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        return ALLOW

    agent_type = data.get("agent_type", data.get("subagent_type", ""))
    cwd = data.get("cwd", os.getcwd())

    if not agent_type:
        return ALLOW

    root = _find_project_root(cwd)

    # Priority 1: explicit .context/ JSONL files
    context_dir = _find_context_dir(cwd)
    entries = []
    source = ""

    if context_dir:
        candidates = [
            os.path.join(context_dir, f"{agent_type}.jsonl"),
            os.path.join(context_dir, "default.jsonl"),
        ]
        for candidate in candidates:
            entries = _read_jsonl(candidate)
            if entries:
                source = ".context/"
                break

    # Priority 2: auto-detect from project structure
    if not entries:
        entries = _auto_detect_entries(root)
        if entries:
            source = "auto-detect"

    if not entries:
        return ALLOW

    # Build context
    context_text = _build_context(entries, root)
    if not context_text:
        return ALLOW

    header = f"[context-inject] Loaded from {source} for {agent_type}:"
    return HookResult(message=f"{header}\n\n{context_text}")
