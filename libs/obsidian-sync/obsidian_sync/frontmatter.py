"""Lenient YAML frontmatter parsing for Obsidian notes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)(.*)\Z", re.DOTALL)


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body) for a markdown file.

    On parse failure (no fence, bad YAML, non-dict YAML): returns ({}, full_text).
    Bad YAML must not block sync.
    """
    text = Path(path).read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, match.group(2)


def build_metadata(
    raw_frontmatter: dict[str, Any],
    vault: str,
    rel_path: str,
) -> dict[str, Any]:
    """Translate Obsidian frontmatter into docvault metadata payload.

    Recognized keys:
      created / date  -> metadata.created_at
      aliases         -> metadata.aliases
      everything else -> metadata.obsidian_extra
    Always sets: vault, rel_path.
    """
    out: dict[str, Any] = {"vault": vault, "rel_path": rel_path}
    extra: dict[str, Any] = {}
    for key, value in raw_frontmatter.items():
        low = key.lower()
        if low in ("created", "date"):
            out["created_at"] = str(value)
        elif low == "aliases":
            out["aliases"] = list(value) if isinstance(value, (list, tuple)) else [str(value)]
        elif low == "tags":
            continue
        else:
            extra[key] = value
    if extra:
        out["obsidian_extra"] = extra
    return out


def extract_tags(raw_frontmatter: dict[str, Any]) -> list[str]:
    """Return frontmatter tags as a flat list of strings (or empty list)."""
    raw = raw_frontmatter.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def extract_title(raw_frontmatter: dict[str, Any], body: str, fallback: str) -> str:
    """Resolve title: frontmatter.title -> first H1 in body -> fallback (e.g. filename stem)."""
    fm_title = raw_frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback
