"""Shorthand parser for quick task input (P0).

Syntax:
  ~30m  → duration_min=30
  ~1h   → duration_min=60
  ~1.5h → duration_min=90
  *p1   → priority=urgent  (*p0=none, *p1=urgent, *p2=high, *p3=medium)
  @work → labels append "work"
  !     → is_frog=True
  #3    → cognitive_cost=3  (1-5)
  ^high → energy_level mapping (^low=1, ^med=3, ^high=5)

Multiple tokens can appear anywhere in the input string.
Remaining text after extraction = title.

Example:
  "Fix login bug ~30m *p1 @work ! #3" →
  {
    "title": "Fix login bug",
    "duration_min": 30,
    "priority": "urgent",
    "labels": ["work"],
    "is_frog": True,
    "cognitive_cost": 3,
  }
"""

from __future__ import annotations

import re

PRIORITY_MAP = {"p0": "none", "p1": "urgent", "p2": "high", "p3": "medium", "p4": "low"}
ENERGY_MAP = {"low": 1, "med": 3, "medium": 3, "high": 5}

# Patterns (order matters — longer patterns first to avoid partial matches)
_DURATION_RE = re.compile(r"~(\d+(?:\.\d+)?)(m|h)\b")
_PRIORITY_RE = re.compile(r"\*p([0-4])\b")
_LABEL_RE = re.compile(r"@(\w+)")
_FROG_RE = re.compile(r"(?<!\w)!(?!\w)")
_COGNITIVE_RE = re.compile(r"#([1-5])\b")
_ENERGY_RE = re.compile(r"\^(low|med|medium|high)\b", re.IGNORECASE)
_REWARD_RE = re.compile(r"\+(\d+)pts?\b")


def parse_shorthand(raw: str) -> dict:
    """Parse shorthand tokens from raw input string.

    Returns dict with extracted fields + "title" (remaining text).
    Only includes keys that were actually found in the input.
    """
    result: dict = {}
    text = raw

    # Duration: ~30m or ~1.5h
    m = _DURATION_RE.search(text)
    if m:
        value = float(m.group(1))
        unit = m.group(2)
        result["duration_min"] = int(value * 60) if unit == "h" else int(value)
        text = text[: m.start()] + text[m.end() :]

    # Priority: *p1
    m = _PRIORITY_RE.search(text)
    if m:
        result["priority"] = PRIORITY_MAP.get(f"p{m.group(1)}", "medium")
        text = text[: m.start()] + text[m.end() :]

    # Labels: @work @home (multiple)
    labels = _LABEL_RE.findall(text)
    if labels:
        result["labels"] = labels
        text = _LABEL_RE.sub("", text)

    # Frog: !
    if _FROG_RE.search(text):
        result["is_frog"] = True
        text = _FROG_RE.sub("", text)

    # Cognitive cost: #3
    m = _COGNITIVE_RE.search(text)
    if m:
        result["cognitive_cost"] = int(m.group(1))
        text = text[: m.start()] + text[m.end() :]

    # Energy level: ^high
    m = _ENERGY_RE.search(text)
    if m:
        result["energy_level"] = ENERGY_MAP.get(m.group(1).lower(), 3)
        text = text[: m.start()] + text[m.end() :]

    # Reward points: +5pts
    m = _REWARD_RE.search(text)
    if m:
        result["reward_points"] = int(m.group(1))
        text = text[: m.start()] + text[m.end() :]

    # Title: remaining text, cleaned up
    title = re.sub(r"\s+", " ", text).strip()
    result["title"] = title

    return result
