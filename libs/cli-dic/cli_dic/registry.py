"""CLI dictionary registry — lookup, list, register."""

from __future__ import annotations

from cli_dic.base import CLIEntry
from cli_dic.claude_code import CLAUDE_CODE
from cli_dic.codex_cli import CODEX_CLI
from cli_dic.gemini_cli import GEMINI_CLI

_REGISTRY: dict[str, CLIEntry] = {
    "claude-code": CLAUDE_CODE,
    "codex-cli": CODEX_CLI,
    "gemini-cli": GEMINI_CLI,
}

_ALIASES: dict[str, str] = {
    "claude": "claude-code",
    "claude-code": "claude-code",
    "cc": "claude-code",
    "anthropic": "claude-code",
    "codex": "codex-cli",
    "codex-cli": "codex-cli",
    "openai": "codex-cli",
    "gemini": "gemini-cli",
    "gemini-cli": "gemini-cli",
    "google": "gemini-cli",
}


def get(name: str) -> CLIEntry:
    """Get a CLI entry by name or alias. Raises KeyError if not found."""
    canonical = _ALIASES.get(name.lower().strip(), name.lower().strip())
    return _REGISTRY[canonical]


def detect_from_command(cmd: str) -> CLIEntry | None:
    """Detect CLI entry from a process command name (e.g., tmux pane_current_command)."""
    if not cmd:
        return None
    basename = cmd.split("/")[-1]
    for entry in _REGISTRY.values():
        if basename in entry.process_names:
            return entry
    return None


def list_entries() -> list[CLIEntry]:
    """Return all registered CLI entries."""
    return list(_REGISTRY.values())


def list_names() -> list[str]:
    """Return all canonical CLI names."""
    return list(_REGISTRY.keys())


def register(entry: CLIEntry, *, aliases: list[str] | None = None) -> None:
    """Register a custom CLI entry."""
    _REGISTRY[entry.name] = entry
    _ALIASES[entry.name] = entry.name
    _ALIASES[entry.binary] = entry.name
    for alias in aliases or []:
        _ALIASES[alias.lower()] = entry.name
