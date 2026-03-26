"""CLI tool detection profiles — registry of prompt/process/indicator patterns.

Each CLIProfile defines how to detect whether a CLI tool is running, idle, or busy.
Profiles are immutable dataclass instances — one per CLI tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CLIProfile:
    """Detection and lifecycle profile for an interactive CLI tool."""

    name: str
    prompt_pattern: re.Pattern
    process_names: frozenset[str]
    detect_semver: bool = False
    processing_indicators: re.Pattern | None = None
    content_indicators: re.Pattern | None = None
    exit_command: str = "/exit"
    startup_template: str = ""


# ── Built-in profiles ──

CLAUDE_CODE = CLIProfile(
    name="claude-code",
    prompt_pattern=re.compile(r"❯"),
    process_names=frozenset({"claude"}),
    detect_semver=True,
    processing_indicators=re.compile(
        r"⏺|✢|✻|Thinking|Processing|Osmosing|Crunching|Deciphering"
    ),
    content_indicators=re.compile(r"❯|⏺|✢|✻|╭─|💰"),
    exit_command="/exit",
    startup_template="claude --dangerously-skip-permissions{model_flag}",
)

GEMINI_CLI = CLIProfile(
    name="gemini-cli",
    prompt_pattern=re.compile(r"❯"),
    process_names=frozenset({"gemini"}),
    exit_command="/exit",
    startup_template="gemini{model_flag}",
)

CODEX_CLI = CLIProfile(
    name="codex-cli",
    prompt_pattern=re.compile(r"❯|>"),
    process_names=frozenset({"codex"}),
    exit_command="/exit",
    startup_template="codex{model_flag}",
)

# ── Registry ──

_REGISTRY: dict[str, CLIProfile] = {
    "claude-code": CLAUDE_CODE,
    "gemini-cli": GEMINI_CLI,
    "codex-cli": CODEX_CLI,
}


def get_profile(name: str) -> CLIProfile:
    """Get a CLI profile by name. Raises KeyError if not found."""
    return _REGISTRY[name]


def register_profile(profile: CLIProfile) -> None:
    """Register a custom CLI profile."""
    _REGISTRY[profile.name] = profile


def list_profiles() -> list[str]:
    """List all registered profile names."""
    return list(_REGISTRY.keys())
