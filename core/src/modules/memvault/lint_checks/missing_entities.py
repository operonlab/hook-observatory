"""Check 4: missing_entities — names that show up in ≥2 blocks but have no
EntityCanonical row.

Heuristic name extraction: pull capitalized multi-word phrases / CamelCase
identifiers from block.content. We do NOT call an LLM (cheap heuristic by
design — wiki-lint is supposed to be a fast pre-filter).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..kg_models import EntityCanonical
from ..models import MemoryBlock

# Match: CamelCase identifiers (length >=4) OR Capitalised Phrases (2-4 words)
_NAME_PATTERN = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3})\b"
)

_STOPWORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "When",
    "Where",
    "What",
    "Why",
    "How",
}


def _extract_names(text: str) -> list[str]:
    if not text:
        return []
    out = []
    seen: set[str] = set()
    for match in _NAME_PATTERN.finditer(text):
        name = match.group(0).strip()
        if not name or name in _STOPWORDS:
            continue
        # Skip very long matches — likely not names
        if len(name) > 80:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


async def check_missing_entities(
    db: AsyncSession,
    space_id: str,
    *,
    min_block_mentions: int = 2,
    sample_blocks: int = 500,
) -> list:
    from ..lint import LintFinding

    bq = (
        select(MemoryBlock.id, MemoryBlock.content)
        .where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.deleted_at.is_(None),
            MemoryBlock.invalid_at.is_(None),
        )
        .order_by(MemoryBlock.created_at.desc())
        .limit(sample_blocks)
    )
    blocks = (await db.execute(bq)).all()

    name_to_blocks: dict[str, set[str]] = {}
    for bid, content in blocks:
        for name in _extract_names(content or ""):
            name_to_blocks.setdefault(name.lower(), set()).add(bid)

    # Existing canonical names + aliases
    eq = select(EntityCanonical.canonical_name, EntityCanonical.aliases).where(
        EntityCanonical.space_id == space_id,
        EntityCanonical.deleted_at.is_(None),
    )
    known: set[str] = set()
    for cname, aliases in (await db.execute(eq)).all():
        if cname:
            known.add(cname.lower())
        for a in aliases or []:
            known.add(a.lower())

    findings: list = []
    for name_lc, block_ids in name_to_blocks.items():
        if len(block_ids) < min_block_mentions:
            continue
        if name_lc in known:
            continue
        # Sample up to 5 block IDs for the metadata
        sample_ids = sorted(block_ids)[:5]
        findings.append(
            LintFinding(
                check="missing_entities",
                severity="info",
                entity_id="",
                entity_type="entity",
                message=(
                    f"Name '{name_lc}' appears in {len(block_ids)} blocks "
                    f"but has no EntityCanonical row"
                ),
                suggested_action=(
                    "Promote this name to an EntityCanonical row, or add it as "
                    "an alias to an existing entity."
                ),
                metadata={
                    "name_lower": name_lc,
                    "mention_count": len(block_ids),
                    "sample_block_ids": sample_ids,
                },
            )
        )

    return findings
