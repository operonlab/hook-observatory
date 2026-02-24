#!/usr/bin/env python3
"""Import V1 KAS Memory data into memvault PostgreSQL tables.

Usage:
    cd core && source ../.venv/bin/activate
    python3 scripts/import_v1_memories.py --kas-dir ~/Claude/projects/kas-memory --space-id default

Reads:
    - memories/YYYY-MM/*.md → memvault.blocks
    - profile.json → memvault.kas_profiles (4 records: knowledge, attitude, skill, summary)
    - knowledge/domains/*.md → memvault.knowledge_domains
    - tags rebuilt from blocks after import

Idempotent: skips blocks whose session_id + topic already exist.
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Add core/src to path so we can import models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shared.models import Base  # noqa: E402
from modules.memvault.models import (  # noqa: E402
    KASProfile,
    KnowledgeDomain,
    MemoryBlock,
    Tag,
)

logger = structlog.get_logger()

# ======================== Parsing ========================

SESSION_HEADER = re.compile(
    r"^## Session:\s*(?P<session_id>\S+)"
    r"(?:\s*\((?P<datetime>[^)]+)\))?\s*$"
)
FIELD_RE = re.compile(r"^\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.+)$")


def parse_memory_file(path: Path) -> list[dict]:
    """Parse a V1 memory .md file into a list of block dicts."""
    blocks: list[dict] = []
    current: dict | None = None
    content_lines: list[str] = []

    def flush():
        nonlocal current, content_lines
        if current:
            current["content"] = "\n".join(content_lines).strip()
            if current["content"]:
                blocks.append(current)
        current = None
        content_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        m = SESSION_HEADER.match(line)
        if m:
            flush()
            current = {
                "session_id": m.group("session_id"),
                "datetime": m.group("datetime"),
                "topic": "",
                "block_type": "technical",
                "tags": [],
                "project": None,
            }
            continue

        if current is None:
            continue

        fm = FIELD_RE.match(line)
        if fm:
            key = fm.group("key").strip().lower()
            value = fm.group("value").strip()
            if key == "topic":
                current["topic"] = value
            elif key == "type":
                current["block_type"] = normalize_type(value)
            elif key == "tags":
                current["tags"] = [t.strip() for t in value.split(",") if t.strip()]
            elif key == "project":
                current["project"] = value
        else:
            content_lines.append(line)

    flush()
    return blocks


def normalize_type(raw: str) -> str:
    """Map V1 free-form types to V2 enum."""
    mapping = {
        "decision": "decision",
        "technical": "technical",
        "preference": "preference",
        "user-preference": "preference",
        "user-correction": "preference",
        "communication": "preference",
        "pattern": "pattern",
        "achievement": "insight",
        "recent-focus": "insight",
        "failed-approach": "technical",
        "insight": "insight",
    }
    return mapping.get(raw.lower(), "technical")


def parse_profile(path: Path) -> dict:
    """Parse V1 profile.json."""
    return json.loads(path.read_text(encoding="utf-8"))


def parse_knowledge_domain(path: Path) -> dict:
    """Parse a V1 knowledge domain .md file."""
    text = path.read_text(encoding="utf-8")
    name = path.stem  # filename without .md
    # Extract key insights count as a rough maturity proxy
    insights = text.count("- ")
    # Extract description from first paragraph after header
    lines = text.splitlines()
    description = ""
    for line in lines:
        if line.startswith(">"):
            description = line.lstrip("> ").strip()
            break

    return {
        "name": name,
        "description": description or None,
        "insights_count": insights,
    }


# ======================== Database Import ========================


async def import_blocks(
    session_factory: async_sessionmaker,
    blocks: list[dict],
    space_id: str,
) -> tuple[int, int]:
    """Import memory blocks. Returns (imported, skipped)."""
    imported = 0
    skipped = 0

    async with session_factory() as db:
        for block in blocks:
            # Idempotency check: session_id + topic
            existing = (
                await db.execute(
                    select(MemoryBlock.id).where(
                        MemoryBlock.space_id == space_id,
                        MemoryBlock.session_id == block["session_id"],
                        MemoryBlock.topic == block["topic"],
                    )
                )
            ).scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            from uuid_utils import uuid7

            db.add(
                MemoryBlock(
                    id=uuid7().hex,
                    space_id=space_id,
                    session_id=block["session_id"],
                    topic=block["topic"],
                    content=block["content"],
                    block_type=block["block_type"],
                    project=block["project"],
                    tags=block["tags"],
                    source="import",
                )
            )
            imported += 1

        await db.commit()
    return imported, skipped


async def import_profiles(
    session_factory: async_sessionmaker,
    profile_data: dict,
    space_id: str,
) -> int:
    """Import KAS profile as 4 profile records. Returns count."""
    from uuid_utils import uuid7

    count = 0
    async with session_factory() as db:
        for profile_type in ("knowledge", "attitude", "skill", "summary"):
            data = profile_data.get(profile_type, profile_data.get("skills", {}))
            if profile_type == "summary":
                data = profile_data.get("memory", {})

            # Upsert: check if exists
            existing = (
                await db.execute(
                    select(KASProfile.id).where(
                        KASProfile.space_id == space_id,
                        KASProfile.profile_type == profile_type,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                await db.execute(
                    text(
                        "UPDATE memvault.kas_profiles SET data = :data, version = version + 1 WHERE id = :id"
                    ).bindparams(data=json.dumps(data), id=existing)
                )
            else:
                db.add(
                    KASProfile(
                        id=uuid7().hex,
                        space_id=space_id,
                        profile_type=profile_type,
                        data=data,
                    )
                )
            count += 1
        await db.commit()
    return count


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

            # Rough maturity: insights_count / 10 capped at 1.0
            maturity = min(domain["insights_count"] / 10.0, 1.0)
            db.add(
                KnowledgeDomain(
                    id=uuid7().hex,
                    space_id=space_id,
                    name=domain["name"],
                    description=domain["description"],
                    maturity=round(maturity, 2),
                )
            )
            imported += 1
        await db.commit()
    return imported, skipped


async def rebuild_tags(
    session_factory: async_sessionmaker, space_id: str
) -> int:
    """Rebuild tag index from blocks."""
    from uuid_utils import uuid7
    from sqlalchemy import delete, func

    async with session_factory() as db:
        # Delete existing tags
        await db.execute(delete(Tag).where(Tag.space_id == space_id))

        # Aggregate tags from blocks
        tag_counts = (
            select(
                func.unnest(MemoryBlock.tags).label("tag_name"),
                func.count().label("cnt"),
            )
            .where(MemoryBlock.space_id == space_id)
            .group_by(text("tag_name"))
            .subquery()
        )

        rows = (await db.execute(select(tag_counts))).all()
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


async def main(kas_dir: str, space_id: str, db_url: str):
    kas_path = Path(kas_dir).expanduser()
    if not kas_path.exists():
        logger.error("KAS directory not found", path=str(kas_path))
        sys.exit(1)

    async_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_async_engine(async_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    logger.info("Starting V1 import", kas_dir=str(kas_path), space_id=space_id)

    # 1. Parse memory files
    memory_dir = kas_path / "memories"
    all_blocks: list[dict] = []
    if memory_dir.exists():
        for md_file in sorted(memory_dir.rglob("*.md")):
            blocks = parse_memory_file(md_file)
            all_blocks.extend(blocks)
            logger.info("Parsed", file=str(md_file.relative_to(kas_path)), blocks=len(blocks))

    logger.info("Total blocks parsed", count=len(all_blocks))

    # 2. Import blocks
    imported, skipped = await import_blocks(session_factory, all_blocks, space_id)
    logger.info("Blocks imported", imported=imported, skipped=skipped)

    # 3. Import profile
    profile_path = kas_path / "profile.json"
    if profile_path.exists():
        profile_data = parse_profile(profile_path)
        count = await import_profiles(session_factory, profile_data, space_id)
        logger.info("Profiles imported", count=count)

    # 4. Import knowledge domains
    domains_dir = kas_path / "knowledge" / "domains"
    if domains_dir.exists():
        domains = [parse_knowledge_domain(f) for f in sorted(domains_dir.glob("*.md"))]
        d_imported, d_skipped = await import_domains(session_factory, domains, space_id)
        logger.info("Domains imported", imported=d_imported, skipped=d_skipped)

    # 5. Rebuild tags
    tag_count = await rebuild_tags(session_factory, space_id)
    logger.info("Tags rebuilt", count=tag_count)

    # Summary
    logger.info(
        "Import complete",
        blocks=imported,
        blocks_skipped=skipped,
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
        default="postgresql://localhost/workshop",
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()
    asyncio.run(main(args.kas_dir, args.space_id, args.db_url))
