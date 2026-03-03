#!/usr/bin/env python3
"""Import V1 KAS Memory data into memvault PostgreSQL tables.

Usage:
    cd core && source ../.venv/bin/activate
    python3 scripts/import_v1_memories.py --kas-dir ~/Claude/projects/kas-memory --space-id default

Reads:
    - memories/YYYY-MM/*.md  → memvault.blocks
    - profile.json           → memvault.kas_profiles (single record per space)
    - knowledge/domains/*.md → memvault.knowledge_domains
    - tags rebuilt from blocks after import

Idempotent: skips blocks whose source_session + first 100 chars of content already exist.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Add core/src to path so we can import models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modules.memvault.embedding import get_embeddings_batch
from modules.memvault.models import (
    KASProfile,
    KnowledgeDomain,
    MemoryBlock,
    Tag,
)

logger = structlog.get_logger()

EMBEDDING_BATCH_SIZE = 10

# ======================== Type Mapping ========================

_TYPE_MAP: dict[str, str] = {
    "decision": "knowledge",
    "technical": "knowledge",
    "preference": "attitude",
    "user-preference": "attitude",
    "user-correction": "attitude",
    "communication": "attitude",
    "pattern": "skill",
    "achievement": "knowledge",
    "recent-focus": "knowledge",
    "failed-approach": "knowledge",
    "insight": "knowledge",
}


def normalize_type(raw: str) -> str:
    """Map V1 free-form types to V2 block_type enum (knowledge|skill|attitude|general)."""
    return _TYPE_MAP.get(raw.strip().lower(), "general")


# ======================== Parsing ========================

SESSION_HEADER = re.compile(
    r"^## Session:\s*(?P<session_id>\S+)"
    r"(?:\s*\((?P<datetime>[^)]+)\))?\s*$"
)
FIELD_RE = re.compile(r"^\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.+)$")


def parse_memory_file(path: Path) -> list[dict]:
    """Parse a V1 memory .md file into a list of block dicts.

    Each block contains:
        source_session  : str   — session UUID from header
        block_type      : str   — normalized V2 type
        tags            : list[str]
        content         : str   — "Topic: <topic>\\n\\n<bullet lines>"
    """
    blocks: list[dict] = []
    current: dict | None = None
    topic: str = ""
    content_lines: list[str] = []

    def flush() -> None:
        nonlocal current, topic, content_lines
        if current is None:
            return
        # Build content: prepend topic header if present
        parts: list[str] = []
        if topic:
            parts.append(f"Topic: {topic}")
        body = "\n".join(content_lines).strip()
        if body:
            if parts:
                parts.append("")  # blank separator
            parts.append(body)
        full_content = "\n".join(parts).strip()
        if full_content:
            current["content"] = full_content
            blocks.append(current)
        current = None
        topic = ""
        content_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        m = SESSION_HEADER.match(line)
        if m:
            flush()
            current = {
                "source_session": m.group("session_id"),
                "block_type": "general",
                "tags": [],
            }
            topic = ""
            content_lines = []
            continue

        if current is None:
            continue

        fm = FIELD_RE.match(line)
        if fm:
            key = fm.group("key").strip().lower()
            value = fm.group("value").strip()
            if key == "topic":
                topic = value
            elif key == "type":
                current["block_type"] = normalize_type(value)
            elif key == "tags":
                current["tags"] = [t.strip() for t in value.split(",") if t.strip()]
            # "project" and other V1-only fields are intentionally dropped
        else:
            content_lines.append(line)

    flush()
    return blocks


def parse_profile(path: Path) -> dict:
    """Parse V1 profile.json into (knowledge_score, attitude_score, skill_score).

    V1 structure is a nested dict; we extract numeric sub-items and average them
    to produce a 0-100 float for each KAS dimension.
    """
    raw: dict = json.loads(path.read_text(encoding="utf-8"))

    def _extract_score(section: dict | None) -> float:
        """Recursively find numeric leaf values and return mean * 100, capped 0-100."""
        if not section or not isinstance(section, dict):
            return 0.0
        values: list[float] = []
        for v in section.values():
            if isinstance(v, (int, float)):
                values.append(float(v))
            elif isinstance(v, dict):
                sub = _extract_score(v)
                if sub > 0:
                    values.append(sub)
        if not values:
            return 0.0
        avg = sum(values) / len(values)
        # Values may already be 0-1 or 0-100; normalise to 0-100
        if avg <= 1.0:
            avg *= 100
        return round(min(max(avg, 0.0), 100.0), 2)

    knowledge_score = _extract_score(raw.get("knowledge"))
    attitude_score = _extract_score(raw.get("attitude"))
    # V1 uses "skills" or "skill"
    skill_score = _extract_score(raw.get("skills") or raw.get("skill"))

    return {
        "knowledge_score": knowledge_score,
        "attitude_score": attitude_score,
        "skill_score": skill_score,
    }


def parse_knowledge_domain(path: Path) -> dict:
    """Parse a V1 knowledge domain .md file.

    Returns:
        name            : str           — filename stem
        description     : str | None    — first blockquote line
        insights_count  : int           — number of bullet points (maturity proxy)
    """
    content = path.read_text(encoding="utf-8")
    name = path.stem
    insights = content.count("- ")
    description: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            description = stripped.lstrip("> ").strip() or None
            break
    return {
        "name": name,
        "description": description,
        "insights_count": insights,
    }


# ======================== Database Import ========================


async def import_blocks(
    session_factory: async_sessionmaker,
    blocks: list[dict],
    space_id: str,
) -> tuple[int, int]:
    """Import memory blocks. Returns (imported, skipped).

    Idempotency key: source_session + first 100 chars of content.
    """
    from uuid_utils import uuid7

    imported = 0
    skipped = 0

    async with session_factory() as db:
        for block in blocks:
            content_prefix = block["content"][:100]

            existing = (
                await db.execute(
                    select(MemoryBlock.id).where(
                        MemoryBlock.space_id == space_id,
                        MemoryBlock.source_session == block["source_session"],
                        MemoryBlock.content.startswith(content_prefix),
                    )
                )
            ).scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            db.add(
                MemoryBlock(
                    id=uuid7().hex,
                    space_id=space_id,
                    source_session=block["source_session"],
                    content=block["content"],
                    block_type=block["block_type"],
                    tags=block["tags"],
                )
            )
            imported += 1

        await db.commit()

    return imported, skipped


async def generate_embeddings(
    session_factory: async_sessionmaker,
    space_id: str,
) -> int:
    """Generate Ollama embeddings for all blocks without one. Returns updated count."""
    updated = 0

    async with session_factory() as db:
        # Fetch all blocks without embeddings
        rows = (
            await db.execute(
                select(MemoryBlock.id, MemoryBlock.content)
                .where(
                    MemoryBlock.space_id == space_id,
                    MemoryBlock.embedding.is_(None),
                )
                .order_by(MemoryBlock.created_at)
            )
        ).all()

    if not rows:
        return 0

    logger.info("Generating embeddings", total=len(rows))

    # Process in batches
    for batch_start in range(0, len(rows), EMBEDDING_BATCH_SIZE):
        batch = rows[batch_start : batch_start + EMBEDDING_BATCH_SIZE]
        texts = [row.content for row in batch]
        embeddings = await get_embeddings_batch(texts)

        async with session_factory() as db:
            for row, embedding in zip(batch, embeddings, strict=False):
                if embedding is not None:
                    await db.execute(
                        update(MemoryBlock)
                        .where(MemoryBlock.id == row.id)
                        .values(embedding=embedding)
                    )
                    updated += 1
            await db.commit()

        logger.info(
            "Embedding batch done",
            batch_end=min(batch_start + EMBEDDING_BATCH_SIZE, len(rows)),
            total=len(rows),
            updated_so_far=updated,
        )

    return updated


async def import_profile(
    session_factory: async_sessionmaker,
    scores: dict,
    space_id: str,
) -> str:
    """Upsert KAS profile (single record per space). Returns 'created' or 'updated'."""
    from uuid_utils import uuid7

    async with session_factory() as db:
        existing_id = (
            await db.execute(select(KASProfile.id).where(KASProfile.space_id == space_id))
        ).scalar_one_or_none()

        if existing_id:
            await db.execute(
                update(KASProfile)
                .where(KASProfile.id == existing_id)
                .values(
                    knowledge_score=scores["knowledge_score"],
                    attitude_score=scores["attitude_score"],
                    skill_score=scores["skill_score"],
                )
            )
            await db.commit()
            return "updated"
        else:
            db.add(
                KASProfile(
                    id=uuid7().hex,
                    space_id=space_id,
                    knowledge_score=scores["knowledge_score"],
                    attitude_score=scores["attitude_score"],
                    skill_score=scores["skill_score"],
                )
            )
            await db.commit()
            return "created"


async def import_domains(
    session_factory: async_sessionmaker,
    domains: list[dict],
    space_id: str,
) -> tuple[int, int]:
    """Import knowledge domains. Returns (imported, skipped)."""
    from uuid_utils import uuid7

    imported = 0
    skipped = 0

    async with session_factory() as db:
        for domain in domains:
            existing = (
                await db.execute(
                    select(KnowledgeDomain.id).where(
                        KnowledgeDomain.space_id == space_id,
                        KnowledgeDomain.name == domain["name"],
                    )
                )
            ).scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            # Rough maturity: bullet count / 10, capped at 1.0
            maturity = round(min(domain["insights_count"] / 10.0, 1.0), 2)
            db.add(
                KnowledgeDomain(
                    id=uuid7().hex,
                    space_id=space_id,
                    name=domain["name"],
                    description=domain["description"],
                    maturity=maturity,
                )
            )
            imported += 1

        await db.commit()

    return imported, skipped


async def rebuild_tags(
    session_factory: async_sessionmaker,
    space_id: str,
) -> int:
    """Rebuild tag index from blocks.tags arrays. Returns tag count."""
    from uuid_utils import uuid7

    async with session_factory() as db:
        # Wipe existing tags for this space
        await db.execute(delete(Tag).where(Tag.space_id == space_id))

        # Aggregate all tag strings from the ARRAY column
        tag_counts_sq = (
            select(
                func.unnest(MemoryBlock.tags).label("tag_name"),
                func.count().label("cnt"),
            )
            .where(MemoryBlock.space_id == space_id)
            .group_by(text("tag_name"))
            .subquery()
        )

        rows = (await db.execute(select(tag_counts_sq))).all()
        for row in rows:
            db.add(
                Tag(
                    id=uuid7().hex,
                    space_id=space_id,
                    name=row.tag_name,
                    usage_count=row.cnt,
                )
            )

        await db.commit()
        return len(rows)


# ======================== Main ========================


async def main(
    kas_dir: str,
    space_id: str,
    db_url: str,
    skip_embeddings: bool,
) -> None:
    kas_path = Path(kas_dir).expanduser()  # noqa: ASYNC240
    if not kas_path.exists():
        logger.error("KAS directory not found", path=str(kas_path))
        sys.exit(1)

    async_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_async_engine(async_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    logger.info("Starting V1 import", kas_dir=str(kas_path), space_id=space_id)

    # ── 1. Parse + import memory blocks ──────────────────────────────────────
    memory_dir = kas_path / "memories"
    all_blocks: list[dict] = []
    if memory_dir.exists():
        for md_file in sorted(memory_dir.rglob("*.md")):
            parsed = parse_memory_file(md_file)
            all_blocks.extend(parsed)
            logger.info(
                "Parsed memory file",
                file=str(md_file.relative_to(kas_path)),
                blocks=len(parsed),
            )
    else:
        logger.warning("memories/ directory not found", path=str(memory_dir))

    logger.info("Total blocks parsed", count=len(all_blocks))

    blocks_imported, blocks_skipped = await import_blocks(session_factory, all_blocks, space_id)
    logger.info("Blocks imported", imported=blocks_imported, skipped=blocks_skipped)

    # ── 2. Generate embeddings ────────────────────────────────────────────────
    if skip_embeddings:
        logger.info("Skipping embedding generation (--skip-embeddings flag)")
        embeddings_updated = 0
    else:
        embeddings_updated = await generate_embeddings(session_factory, space_id)
        logger.info("Embeddings generated", updated=embeddings_updated)

    # ── 3. Import KAS profile ─────────────────────────────────────────────────
    profile_path = kas_path / "profile.json"
    if profile_path.exists():
        scores = parse_profile(profile_path)
        action = await import_profile(session_factory, scores, space_id)
        logger.info(
            "KAS profile imported",
            action=action,
            knowledge_score=scores["knowledge_score"],
            attitude_score=scores["attitude_score"],
            skill_score=scores["skill_score"],
        )
    else:
        logger.warning("profile.json not found", path=str(profile_path))

    # ── 4. Import knowledge domains ───────────────────────────────────────────
    domains_dir = kas_path / "knowledge" / "domains"
    domains_imported = domains_skipped = 0
    if domains_dir.exists():
        domains = [parse_knowledge_domain(f) for f in sorted(domains_dir.glob("*.md"))]
        domains_imported, domains_skipped = await import_domains(session_factory, domains, space_id)
        logger.info("Domains imported", imported=domains_imported, skipped=domains_skipped)
    else:
        logger.warning("knowledge/domains/ directory not found", path=str(domains_dir))

    # ── 5. Rebuild tag index ──────────────────────────────────────────────────
    tag_count = await rebuild_tags(session_factory, space_id)
    logger.info("Tags rebuilt", count=tag_count)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info(
        "Import complete",
        blocks_imported=blocks_imported,
        blocks_skipped=blocks_skipped,
        embeddings_updated=embeddings_updated,
        domains_imported=domains_imported,
        domains_skipped=domains_skipped,
        tags=tag_count,
    )

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import V1 KAS Memory into memvault")
    parser.add_argument(
        "--kas-dir",
        default="~/Claude/projects/kas-memory",
        help="Path to V1 KAS memory directory",
    )
    parser.add_argument(
        "--space-id",
        default="default",
        help="Target space ID",
    )
    parser.add_argument(
        "--db-url",
        default="postgresql://joneshong:REDACTED@localhost/workshop",
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip Ollama embedding generation (useful for dry runs)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.kas_dir, args.space_id, args.db_url, args.skip_embeddings))
