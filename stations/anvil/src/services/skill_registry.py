"""Business logic for skill CRUD and auto-registration from filesystem."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from db import Skill, SkillVersion, async_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import config

logger = logging.getLogger("anvil.skill_registry")

# Regex for YAML frontmatter in SKILL.md
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*):\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse simple YAML frontmatter from SKILL.md content.

    Handles flat key-value pairs. For nested structures like io/tags,
    returns them as raw strings (callers parse further if needed).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    fm_text = match.group(1)
    result: dict[str, Any] = {}
    for kv_match in _KV_RE.finditer(fm_text):
        key = kv_match.group(1)
        value = kv_match.group(2).strip()
        # Strip surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        result[key] = value

    return result


def _extract_description(content: str) -> str | None:
    """Extract description from first non-frontmatter paragraph."""
    # Remove frontmatter
    cleaned = _FRONTMATTER_RE.sub("", content).strip()
    if not cleaned:
        return None

    # Take first non-empty paragraph (up to heading or blank line)
    lines: list[str] = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Skip headings, take content after
            continue
        if not stripped and lines:
            break
        if stripped:
            lines.append(stripped)

    return " ".join(lines)[:500] if lines else None


def _parse_tags(raw: str) -> list[str]:
    """Parse tags from frontmatter value like '[tag1, tag2]' or 'tag1, tag2'."""
    cleaned = raw.strip("[]")
    return [t.strip().strip("'\"") for t in cleaned.split(",") if t.strip()]


def _compute_md_hash(content: str) -> str:
    """SHA-256 hash of SKILL.md content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


async def scan_and_register_skills() -> list[dict[str, Any]]:
    """Scan skills_dir and register/update all skills found.

    Returns a list of dicts with {name, version, status} for each processed skill.
    """
    skills_dir = config.skills_dir
    if not skills_dir.exists():
        logger.warning("Skills directory does not exist: %s", skills_dir)
        return []

    registered: list[dict[str, Any]] = []

    async with async_session() as db:
        for skill_path in sorted(skills_dir.iterdir()):
            if not skill_path.is_dir():
                continue

            skill_md = skill_path / "SKILL.md"
            if not skill_md.exists():
                continue

            name = skill_path.name
            content = skill_md.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(content)

            version = fm.get("version")
            description = fm.get("description") or _extract_description(content)
            tags = _parse_tags(fm["tags"]) if "tags" in fm else []
            md_hash = _compute_md_hash(content)

            # Upsert skill
            values: dict[str, Any] = {
                "name": name,
                "version": version,
                "description": description,
                "tags": tags,
                "status": "active",
            }
            stmt = pg_insert(Skill).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "version": version,
                    "description": description,
                    "tags": tags,
                },
            )
            await db.execute(stmt)

            # Record version snapshot if version is present
            if version:
                # Check if this version+hash combo already exists
                existing = await db.execute(
                    select(SkillVersion).where(
                        SkillVersion.skill_name == name,
                        SkillVersion.version == version,
                        SkillVersion.skill_md_hash == md_hash,
                    )
                )
                if existing.scalar_one_or_none() is None:
                    sv = SkillVersion(
                        skill_name=name,
                        version=version,
                        skill_md_hash=md_hash,
                    )
                    db.add(sv)

            registered.append({"name": name, "version": version, "status": "registered"})

        await db.commit()

    logger.info("Scanned and registered %d skills from %s", len(registered), skills_dir)
    return registered
