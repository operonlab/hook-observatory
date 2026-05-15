"""Lenient YAML frontmatter parsing for Obsidian notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body) for a markdown file.

    On parse failure: returns ({}, full_text). Bad YAML must not block sync.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        import frontmatter as _fm
    except ImportError:
        return {}, text

    try:
        post = _fm.loads(text)
        meta = dict(post.metadata or {})
        return meta, post.content
    except Exception:
        return {}, text


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
