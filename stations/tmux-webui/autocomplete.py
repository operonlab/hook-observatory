"""Autocomplete engine: path, command history, skill completion."""

import logging
import os
import re

logger = logging.getLogger("tmux-webui")

# ── Path completion ──


def complete_path(partial: str, max_results: int = 20) -> list[dict]:
    """Complete filesystem paths from a partial string."""
    expanded = os.path.expanduser(partial)

    if os.path.isdir(expanded) and not partial.endswith("/"):
        expanded += "/"

    if expanded.endswith("/"):
        base_dir = expanded
        prefix = ""
    else:
        base_dir = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded).lower()

    results = []
    try:
        entries = os.listdir(base_dir)
        for entry in sorted(entries):
            if entry.startswith(".") and not prefix.startswith("."):
                continue
            if prefix and not entry.lower().startswith(prefix):
                continue
            full = os.path.join(base_dir, entry)
            is_dir = os.path.isdir(full)
            display = entry + ("/" if is_dir else "")
            # Reconstruct the completed path
            if expanded.endswith("/"):
                completed = partial + display
            else:
                completed = os.path.join(os.path.dirname(partial) or "", display)
                if partial.startswith("~/"):
                    completed = "~/" + os.path.relpath(full, os.path.expanduser("~"))
                    if is_dir:
                        completed += "/"
            results.append({
                "text": completed,
                "display": display,
                "type": "dir" if is_dir else "file",
                "category": "path",
            })
            if len(results) >= max_results:
                break
    except PermissionError:
        pass
    except FileNotFoundError:
        pass

    return results


# ── Command history completion ──

_history_cache: list[str] = []
_history_mtime: float = 0


def _load_history() -> list[str]:
    """Load unique commands from zsh history (most recent first)."""
    global _history_cache, _history_mtime

    hist_path = os.path.expanduser("~/.zsh_history")
    if not os.path.exists(hist_path):
        return _history_cache

    try:
        mtime = os.path.getmtime(hist_path)
        if mtime == _history_mtime and _history_cache:
            return _history_cache

        _history_mtime = mtime
        commands = []
        seen = set()

        with open(hist_path, "rb") as f:
            raw = f.read()

        # zsh history format: ": timestamp:0;command"
        for line in raw.decode("utf-8", errors="replace").splitlines():
            m = re.match(r"^: \d+:\d+;(.+)$", line)
            cmd = m.group(1).strip() if m else line.strip()
            if cmd and cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)

        # Most recent first
        commands.reverse()
        _history_cache = commands[:5000]
        return _history_cache

    except Exception as e:
        logger.debug("Failed to load zsh history: %s", e)
        return _history_cache


def complete_command(partial: str, max_results: int = 15) -> list[dict]:
    """Complete from zsh command history."""
    history = _load_history()
    query = partial.lower()
    results = []

    for cmd in history:
        if query in cmd.lower():
            results.append({
                "text": cmd,
                "display": cmd[:80] + ("..." if len(cmd) > 80 else ""),
                "type": "history",
                "category": "history",
            })
            if len(results) >= max_results:
                break

    return results


# ── Skill completion ──

_skill_cache: list[dict] = []
_skill_mtime: float = 0

# Category mapping for known skills
SKILL_CATEGORIES = {
    "smart-search": "Search", "brainstorming": "Search",
    "competitive-intel": "Search", "model-mentor": "Search",
    "meeting-insights": "Search", "company-intel": "Search",
    "diagram-gen": "Visual", "image-gen": "Visual",
    "image-edit": "Visual", "image-prompt": "Visual",
    "canvas-design": "Visual", "frontend-design": "Visual",
    "theme-factory": "Visual", "brand-guidelines": "Visual",
    "ui-audit": "Visual",
    "pdf": "Document", "xlsx": "Document", "pptx": "Document", "docx": "Document",
    "ocr": "Document",
    "content-writer": "Writing", "marketing-copy": "Writing",
    "doc-coauthoring": "Writing", "readme-gen": "Writing",
    "changelog-gen": "Writing", "social-content": "Writing",
    "systematic-debugging": "Dev", "tdd": "Dev",
    "verification-before-completion": "Dev", "spec-kit": "Dev",
    "mcp-builder": "Dev", "git-worktrees": "Dev",
    "maestro": "Orchestr", "team-tasks": "Orchestr",
    "claude-code-headless": "Orchestr", "codex-cli-headless": "Orchestr",
    "gemini-cli-headless": "Orchestr", "scheduler": "Orchestr",
    "create-skill": "Skills", "skill-optimizer": "Skills",
    "skill-publisher": "Skills", "skill-catalog": "Skills",
    "skill-tester": "Skills",
    "notebookllm": "Notebook", "notebookllm-visual": "Notebook",
    "sync-config": "Infra", "keybindings-help": "Infra",
}


def _scan_skills() -> list[dict]:
    """Scan ~/.claude/skills/ for available skills."""
    global _skill_cache, _skill_mtime

    skills_dir = os.path.expanduser("~/.claude/skills")
    if not os.path.isdir(skills_dir):
        return _skill_cache

    try:
        mtime = os.path.getmtime(skills_dir)
        if mtime == _skill_mtime and _skill_cache:
            return _skill_cache

        _skill_mtime = mtime
        skills = []
        for entry in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, entry, "SKILL.md")
            if os.path.isfile(skill_md):
                cat = SKILL_CATEGORIES.get(entry, "Other")
                skills.append({
                    "name": entry,
                    "category": cat,
                })

        _skill_cache = skills
        return _skill_cache
    except Exception as e:
        logger.debug("Failed to scan skills: %s", e)
        return _skill_cache


def complete_skill(partial: str, max_results: int = 20) -> list[dict]:
    """Complete skill names from ~/.claude/skills/."""
    skills = _scan_skills()
    query = partial.lower().lstrip("/")
    results = []

    for sk in skills:
        if query in sk["name"].lower():
            results.append({
                "text": "/" + sk["name"],
                "display": "/" + sk["name"],
                "type": "skill",
                "category": sk["category"],
            })
            if len(results) >= max_results:
                break

    return results


# ── Unified completion ──


def complete(text: str) -> list[dict]:
    """Route completion based on input pattern."""
    text = text.strip()
    if not text:
        return []

    # Skill completion: starts with /
    if text.startswith("/"):
        return complete_skill(text)

    # Path completion: starts with ~, /, or .
    if text.startswith(("~", "/", "./")):
        return complete_path(text)

    # Otherwise: command history
    return complete_command(text)
