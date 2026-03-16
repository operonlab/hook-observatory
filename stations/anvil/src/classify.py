"""Skill invocation classifier.

Determines category for each invocation based on filesystem checks
and known patterns. Categories: skill, command, alias, test, unknown.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

HOME = os.path.expanduser("~")
SKILLS_DIR = Path(HOME) / ".claude" / "skills"
COMMANDS_DIR = Path(HOME) / ".claude" / "commands"

# Known compound commands (not a 1:1 skill mapping)
KNOWN_COMMANDS = {
    "dev",
    "r",
    "sandbox",
    "changelog",
    "readme",
    "skill-catalog",
    "skill-test",
    "codex-headless",
    "gemini-headless",
    "claude-headless",
    "image-prompt",
    "screen-record",
    "video-mix",
    "review-claudemd",
}

# Test patterns
_TEST_PREFIXES = ("_",)
_TEST_EXACT = {"test-skill", "test-verify", "general-purpose", "commit"}
_TEST_DIGIT = re.compile(r"^skill-\d+$")


@lru_cache(maxsize=256)
def classify(skill_name: str) -> str:
    """Return category for a skill invocation name.

    Returns one of: 'skill', 'command', 'test', 'unknown'
    """
    # Test entries
    if any(skill_name.startswith(p) for p in _TEST_PREFIXES):
        return "test"
    if skill_name in _TEST_EXACT:
        return "test"
    if _TEST_DIGIT.match(skill_name):
        return "test"

    # Real skill (has SKILL.md)
    if (SKILLS_DIR / skill_name / "SKILL.md").exists():
        return "skill"

    # Command (has .md in commands/)
    if (COMMANDS_DIR / f"{skill_name}.md").exists():
        return "command"

    # Known commands that might not have .md files
    if skill_name in KNOWN_COMMANDS:
        return "command"

    return "unknown"
