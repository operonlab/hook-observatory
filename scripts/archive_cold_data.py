"""Cold data archiving script — 3-dimensional decision tree.

Scans hot tables for data exceeding age/size thresholds and archives:
  - COLD-ARCHIVE: entire row moves to archive table, vector deleted
  - COLD-BLOB: content uploaded to RustFS (S3), replaced with s3:// reference

Decision tree:
  Is row > {age_days} old?
    ├─ No  → HOT (skip)
    └─ Yes → Is content > {blob_threshold_bytes}?
         ├─ Yes → COLD-BLOB (upload content to S3, metadata to archive table)
         └─ No  → COLD-ARCHIVE (full row to archive table)

Usage:
    python3 scripts/archive_cold_data.py                    # dry-run (default)
    python3 scripts/archive_cold_data.py --execute          # actually archive
    python3 scripts/archive_cold_data.py --age-days 180     # custom age threshold
    python3 scripts/archive_cold_data.py --blob-threshold 5120  # custom size (bytes)
    python3 scripts/archive_cold_data.py --module memvault  # single module only

Designed to run weekly via cron or HEARTBEAT event.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add core to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("archive_cold_data")

# Defaults
DEFAULT_AGE_DAYS = 365
DEFAULT_BLOB_THRESHOLD = 10240  # 10 KB


# ======================== Archive Functions ========================


async def archive_memvault_blocks(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Archive old memvault blocks."""
    from src.modules.memvault.models import BlockArchive, BlockEmbedding, MemoryBlock

    stats = {"scanned": 0, "cold_archive": 0, "cold_blob": 0, "skipped": 0, "errors": 0}

    q = select(MemoryBlock).where(MemoryBlock.created_at < str(cutoff))
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    for block in rows:
        try:
            content = block.content or ""
            content_size = len(content.encode("utf-8"))
            archive_type = "cold-blob" if content_size > blob_threshold else "cold-archive"
            now_str = datetime.now(timezone.utc).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive block %s (%s, %d bytes)",
                    block.id, archive_type, content_size,
                )
                stats[archive_type.replace("-", "_")] += 1
                continue

            archived_content = content

            # COLD-BLOB: upload content to S3
            if archive_type == "cold-blob" and s3_upload_fn:
                s3_uri = await s3_upload_fn(
                    f"memvault/{block.id}", content
                )
                if s3_uri:
                    archived_content = s3_uri
                else:
                    logger.warning("S3 upload failed for block %s, falling back to cold-archive", block.id)
                    archive_type = "cold-archive"

            # Insert into archive table
            db.add(BlockArchive(
                id=block.id,
                space_id=block.space_id,
                created_by=block.created_by,
                created_at=str(block.created_at),
                updated_at=str(block.updated_at),
                source_session=block.source_session,
                content=archived_content,
                block_type=block.block_type,
                tags=block.tags or [],
                confidence=block.confidence,
                archived_at=now_str,
                archive_type=archive_type,
            ))

            # Delete embedding sub-table entry (if exists)
            await db.execute(
                delete(BlockEmbedding).where(BlockEmbedding.block_id == block.id)
            )

            # Delete original row (CASCADE removes block_embeddings too if not already)
            await db.execute(
                delete(MemoryBlock).where(MemoryBlock.id == block.id)
            )

            stats[archive_type.replace("-", "_")] += 1
            logger.info("Archived block %s → %s", block.id, archive_type)

        except Exception as e:
            stats["errors"] += 1
            logger.error("Failed to archive block %s: %s", block.id, e)

    return stats


async def archive_intelflow_reports(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Archive old intelflow reports."""
    from src.modules.intelflow.models import Report, ReportArchive, ReportEmbedding

    stats = {"scanned": 0, "cold_archive": 0, "cold_blob": 0, "skipped": 0, "errors": 0}

    q = select(Report).where(Report.created_at < str(cutoff))
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    for report in rows:
        try:
            content = report.content or ""
            content_size = len(content.encode("utf-8"))
            archive_type = "cold-blob" if content_size > blob_threshold else "cold-archive"
            now_str = datetime.now(timezone.utc).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive report %s '%s' (%s, %d bytes)",
                    report.id, report.title[:40], archive_type, content_size,
                )
                stats[archive_type.replace("-", "_")] += 1
                continue

            archived_content = content

            if archive_type == "cold-blob" and s3_upload_fn:
                s3_uri = await s3_upload_fn(
                    f"intelflow/{report.id}", content
                )
                if s3_uri:
                    archived_content = s3_uri
                else:
                    logger.warning("S3 upload failed for report %s, falling back to cold-archive", report.id)
                    archive_type = "cold-archive"

            db.add(ReportArchive(
                id=report.id,
                space_id=report.space_id,
                created_by=report.created_by,
                created_at=str(report.created_at),
                updated_at=str(report.updated_at),
                title=report.title,
                query=report.query,
                content=archived_content,
                sources=report.sources,
                tags=report.tags or [],
                skill_name=report.skill_name,
                archived_at=now_str,
                archive_type=archive_type,
            ))

            # Delete embedding sub-table entry
            await db.execute(
                delete(ReportEmbedding).where(ReportEmbedding.report_id == report.id)
            )

            # Delete original row
            await db.execute(
                delete(Report).where(Report.id == report.id)
            )

            stats[archive_type.replace("-", "_")] += 1
            logger.info("Archived report %s → %s", report.id, archive_type)

        except Exception as e:
            stats["errors"] += 1
            logger.error("Failed to archive report %s: %s", report.id, e)

    return stats


async def archive_intelflow_briefings(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Archive old intelflow briefings."""
    from src.modules.intelflow.models import Briefing, BriefingArchive

    stats = {"scanned": 0, "cold_archive": 0, "cold_blob": 0, "skipped": 0, "errors": 0}

    q = select(Briefing).where(Briefing.created_at < str(cutoff))
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    for briefing in rows:
        try:
            # Estimate JSONB size for blob threshold check
            import json
            raw_size = len(json.dumps(briefing.raw_data or {}).encode("utf-8"))
            analyses_size = len(json.dumps(briefing.analyses or {}).encode("utf-8"))
            debate_size = len((briefing.debate or "").encode("utf-8"))
            total_size = raw_size + analyses_size + debate_size
            archive_type = "cold-blob" if total_size > blob_threshold else "cold-archive"
            now_str = datetime.now(timezone.utc).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive briefing %s date=%s domain=%s (%s, %d bytes)",
                    briefing.id, briefing.date, briefing.domain, archive_type, total_size,
                )
                stats[archive_type.replace("-", "_")] += 1
                continue

            db.add(BriefingArchive(
                id=briefing.id,
                space_id=briefing.space_id,
                created_by=briefing.created_by,
                created_at=str(briefing.created_at),
                updated_at=str(briefing.updated_at),
                date=briefing.date,
                domain=briefing.domain,
                raw_data=briefing.raw_data,
                analyses=briefing.analyses,
                debate=briefing.debate,
                archived_at=now_str,
                archive_type=archive_type,
            ))

            # Delete original row
            await db.execute(
                delete(Briefing).where(Briefing.id == briefing.id)
            )

            stats[archive_type.replace("-", "_")] += 1
            logger.info("Archived briefing %s → %s", briefing.id, archive_type)

        except Exception as e:
            stats["errors"] += 1
            logger.error("Failed to archive briefing %s: %s", briefing.id, e)

    return stats


# ======================== Main ========================


async def run_archiving(
    db_url: str,
    age_days: int,
    blob_threshold: int,
    dry_run: bool,
    modules: list[str] | None = None,
) -> dict:
    """Main archiving entry point."""
    # Async engine
    async_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
    all_modules = modules or ["memvault", "intelflow"]

    # S3 upload function (only for actual execution)
    s3_upload_fn = None
    if not dry_run:
        try:
            from src.shared.storage import ensure_bucket, upload_blob
            bucket_ok = await ensure_bucket()
            if bucket_ok:
                s3_upload_fn = upload_blob
                logger.info("S3 storage available — COLD-BLOB archiving enabled")
            else:
                logger.warning("S3 bucket unavailable — all entries will use COLD-ARCHIVE")
        except Exception as e:
            logger.warning("S3 not available (%s) — all entries will use COLD-ARCHIVE", e)

    results = {}

    async with async_session() as db:
        async with db.begin():
            if "memvault" in all_modules:
                logger.info("=== Archiving memvault blocks (cutoff: %s) ===", cutoff.date())
                results["memvault_blocks"] = await archive_memvault_blocks(
                    db, cutoff, blob_threshold, dry_run, s3_upload_fn
                )

            if "intelflow" in all_modules:
                logger.info("=== Archiving intelflow reports (cutoff: %s) ===", cutoff.date())
                results["intelflow_reports"] = await archive_intelflow_reports(
                    db, cutoff, blob_threshold, dry_run, s3_upload_fn
                )

                logger.info("=== Archiving intelflow briefings (cutoff: %s) ===", cutoff.date())
                results["intelflow_briefings"] = await archive_intelflow_briefings(
                    db, cutoff, blob_threshold, dry_run, s3_upload_fn
                )

    await engine.dispose()
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Archive cold data from PostgreSQL to archive tables + RustFS"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually archive (default is dry-run)",
    )
    parser.add_argument(
        "--age-days", type=int, default=DEFAULT_AGE_DAYS,
        help=f"Archive rows older than N days (default: {DEFAULT_AGE_DAYS})",
    )
    parser.add_argument(
        "--blob-threshold", type=int, default=DEFAULT_BLOB_THRESHOLD,
        help=f"Content size (bytes) above which to use COLD-BLOB (default: {DEFAULT_BLOB_THRESHOLD})",
    )
    parser.add_argument(
        "--module", type=str, choices=["memvault", "intelflow"], action="append",
        dest="modules", help="Limit to specific module (can repeat)",
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="Database URL (default: from CORE_DB_URL or config)",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    if dry_run:
        logger.info("=== DRY RUN MODE (use --execute to actually archive) ===")
    else:
        logger.info("=== EXECUTE MODE — changes will be committed ===")

    # Resolve DB URL
    import os
    db_url = args.db_url or os.environ.get("CORE_DB_URL")
    if not db_url:
        try:
            from src.config import settings
            db_url = settings.db_url
        except Exception:
            db_url = "postgresql://joneshong:REDACTED@localhost/workshop"

    results = asyncio.run(run_archiving(
        db_url=db_url,
        age_days=args.age_days,
        blob_threshold=args.blob_threshold,
        dry_run=dry_run,
        modules=args.modules,
    ))

    # Print summary
    print("\n" + "=" * 60)
    print("ARCHIVING SUMMARY")
    print("=" * 60)
    total_archived = 0
    total_errors = 0
    for table, stats in results.items():
        archived = stats["cold_archive"] + stats["cold_blob"]
        total_archived += archived
        total_errors += stats["errors"]
        print(f"\n{table}:")
        print(f"  Scanned:      {stats['scanned']}")
        print(f"  Cold-Archive:  {stats['cold_archive']}")
        print(f"  Cold-Blob:     {stats['cold_blob']}")
        print(f"  Errors:        {stats['errors']}")

    print(f"\nTotal archived: {total_archived}")
    print(f"Total errors:   {total_errors}")
    if dry_run:
        print("\n(Dry run — no changes made)")
    print("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
