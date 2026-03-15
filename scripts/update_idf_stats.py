#!/usr/bin/env python3
"""Background job: compute corpus-wide IDF stats and store in Redis.

Usage:
    python scripts/update_idf_stats.py [--services memvault,intelflow]

Runs once then exits. Scheduled via Cronicle: ws-search-idf-update (daily 3:30AM).
"""

import asyncio
import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("update_idf_stats")


async def collect_texts(service: str) -> list[str]:
    """Collect all document texts for a service from PostgreSQL."""
    from core.src.shared.database import async_session_factory
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    texts: list[str] = []

    try:
        async with async_session_factory() as db:
            db: AsyncSession
            if service == "memvault":
                from core.src.modules.memvault.models import MemoryBlock

                rows = (await db.execute(select(MemoryBlock.content))).scalars().all()
                texts = [r for r in rows if r]
            elif service == "intelflow":
                from core.src.modules.intelflow.models import Report

                rows = (
                    (await db.execute(select(Report.content).where(Report.content.isnot(None))))
                    .scalars()
                    .all()
                )
                texts = list(rows)
            else:
                logger.warning("Unknown service %s — skipping", service)
    except Exception as e:
        logger.error("Failed to collect texts from %s: %s", service, e)

    return texts


async def main(services: list[str]) -> None:
    from core.src.shared.sparse_tokenizer import compute_corpus_idf, store_idf_to_redis

    all_texts: list[str] = []

    for svc in services:
        logger.info("Collecting texts from %s...", svc)
        texts = await collect_texts(svc)
        logger.info("  %s: %d documents", svc, len(texts))
        all_texts.extend(texts)

    if not all_texts:
        logger.warning("No texts collected — skipping IDF computation")
        return

    logger.info("Computing IDF stats from %d total documents...", len(all_texts))
    idf_stats = await compute_corpus_idf(all_texts)
    logger.info("Computed IDF for %d unique tokens", len(idf_stats))

    ok = await store_idf_to_redis(idf_stats)
    if ok:
        logger.info("IDF stats stored in Redis (24h TTL)")
    else:
        logger.error("Failed to store IDF stats")
        sys.exit(1)


if __name__ == "__main__":
    parser = ArgumentParser(description="Compute and store corpus IDF stats")
    parser.add_argument(
        "--services",
        default="memvault,intelflow",
        help="Comma-separated service names (default: memvault,intelflow)",
    )
    args = parser.parse_args()
    services = [s.strip() for s in args.services.split(",")]
    asyncio.run(main(services))
