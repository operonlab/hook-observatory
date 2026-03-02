"""Four-tier data lifecycle script — Hot / Warm / Cold / Frozen.

Manages the full lifecycle of data across four tiers:
  Hot    — Full indexes (HNSW + GIN + B-tree), fastest search
  Warm   — Main table kept, HNSW embedding deleted, GIN+B-tree active
  Cold   — Row moved to archive table, content may be S3 ref
  Frozen — Minimal metadata in frozen table + S3 full content

Phases:
  Phase 1 (Hot -> Warm): Delete embedding sub-table entries for aged rows
  Phase 2 (Warm -> Cold): Move rows to archive tables, optionally S3 blob
  Phase 3 (Cold -> Frozen): Upload archive rows to S3, keep minimal metadata

Usage:
    python3 scripts/archive_cold_data.py                    # dry-run
    python3 scripts/archive_cold_data.py --execute          # run all
    python3 scripts/archive_cold_data.py --phase 1          # hot->warm
    python3 scripts/archive_cold_data.py --phase 2          # warm->cold
    python3 scripts/archive_cold_data.py --module memvault  # single module
    python3 scripts/archive_cold_data.py --phase all        # all phases

Designed to run weekly via cron or HEARTBEAT event.
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add core to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.shared.tier_config import (
    BLOB_THRESHOLD_BYTES,
    LIFECYCLE_BATCH_SIZE,
    TIER_THRESHOLDS,
    get_threshold,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("archive_cold_data")


# ====================== Phase 0: Dry-Run Report ======================


async def _count_candidates(
    db: AsyncSession,
    model,
    cutoff: datetime,
) -> int:
    """Count rows older than cutoff in the given model."""
    q = select(func.count()).select_from(model).where(
        model.created_at < str(cutoff)
    )
    result = await db.execute(q)
    return result.scalar() or 0


async def _count_embedding_candidates(
    db: AsyncSession,
    embedding_model,
    main_model,
    fk_col_name: str,
    cutoff: datetime,
) -> int:
    """Count embedding rows whose parent is older than cutoff."""
    fk_col = getattr(embedding_model, fk_col_name)
    q = (
        select(func.count())
        .select_from(embedding_model)
        .where(
            fk_col.in_(
                select(main_model.id).where(
                    main_model.created_at < str(cutoff)
                )
            )
        )
    )
    result = await db.execute(q)
    return result.scalar() or 0


async def _count_archive_candidates(
    db: AsyncSession,
    archive_model,
    cutoff: datetime,
) -> int:
    """Count archive rows older than cutoff (cold->frozen)."""
    q = select(func.count()).select_from(archive_model).where(
        archive_model.archived_at < str(cutoff)
    )
    result = await db.execute(q)
    return result.scalar() or 0


async def print_lifecycle_report(
    db: AsyncSession,
    modules: list[str],
    now: datetime,
) -> None:
    """Print Phase 0 dry-run summary of all tiers."""
    print("\n=== Four-Tier Lifecycle Report ===")

    for mod in modules:
        t = get_threshold(mod)
        hot_cutoff = now - timedelta(days=t.hot_days)
        warm_cutoff = now - timedelta(days=t.warm_days)
        cold_cutoff = now - timedelta(days=t.cold_days)

        print(
            f"\nModule: {mod} "
            f"(hot={t.hot_days}d, warm={t.warm_days}d, "
            f"cold={t.cold_days}d)"
        )

        if mod == "memvault":
            from src.modules.memvault.models import (
                BlockArchive,
                BlockEmbedding,
                MemoryBlock,
            )

            emb_count = await _count_embedding_candidates(
                db, BlockEmbedding, MemoryBlock,
                "block_id", hot_cutoff,
            )
            archive_count = await _count_candidates(
                db, MemoryBlock, warm_cutoff,
            )
            frozen_count = await _count_archive_candidates(
                db, BlockArchive, cold_cutoff,
            )
            print(
                f"  Hot -> Warm candidates: "
                f"{emb_count} (embeddings to delete)"
            )
            print(
                f"  Warm -> Cold candidates: "
                f"{archive_count} (rows to archive)"
            )
            print(
                f"  Cold -> Frozen candidates: "
                f"{frozen_count} (rows to freeze)"
            )

        elif mod == "intelflow":
            from src.modules.intelflow.models import (
                Briefing,
                BriefingArchive,
                Report,
                ReportArchive,
                ReportEmbedding,
            )

            emb_count = await _count_embedding_candidates(
                db, ReportEmbedding, Report,
                "report_id", hot_cutoff,
            )
            report_count = await _count_candidates(
                db, Report, warm_cutoff,
            )
            briefing_count = await _count_candidates(
                db, Briefing, warm_cutoff,
            )
            frozen_r = await _count_archive_candidates(
                db, ReportArchive, cold_cutoff,
            )
            frozen_b = await _count_archive_candidates(
                db, BriefingArchive, cold_cutoff,
            )
            print(
                f"  Hot -> Warm candidates: "
                f"{emb_count} (report embeddings to delete)"
            )
            print(
                f"  Warm -> Cold candidates: "
                f"{report_count} reports, "
                f"{briefing_count} briefings"
            )
            print(
                f"  Cold -> Frozen candidates: "
                f"{frozen_r} reports, "
                f"{frozen_b} briefings"
            )

    print()


# ============== Phase 1: Hot -> Warm (delete embeddings) ==============


async def warm_memvault_blocks(
    db: AsyncSession,
    cutoff: datetime,
    dry_run: bool,
) -> dict:
    """Phase 1: Delete embedding sub-table entries for old blocks.

    Rows stay in the main blocks table; only the HNSW-indexed
    embedding vectors in block_embeddings are removed.
    """
    from src.modules.memvault.models import (
        BlockEmbedding,
        MemoryBlock,
    )

    stats = {"scanned": 0, "embeddings_deleted": 0, "errors": 0}

    # Find block IDs whose parent row is older than cutoff
    old_ids_q = select(MemoryBlock.id).where(
        MemoryBlock.created_at < str(cutoff)
    )
    # Count matching embeddings
    count_q = (
        select(func.count())
        .select_from(BlockEmbedding)
        .where(BlockEmbedding.block_id.in_(old_ids_q))
    )
    total = (await db.execute(count_q)).scalar() or 0
    stats["scanned"] = total

    if total == 0:
        logger.info("[Phase 1] memvault: no embeddings to warm")
        return stats

    if dry_run:
        logger.info(
            "[DRY-RUN] [Phase 1] Would delete %d block embeddings",
            total,
        )
        stats["embeddings_deleted"] = total
        return stats

    # Batched delete
    offset = 0
    while True:
        batch_ids_q = (
            select(MemoryBlock.id)
            .where(MemoryBlock.created_at < str(cutoff))
            .limit(LIFECYCLE_BATCH_SIZE)
            .offset(offset)
        )
        batch_ids = (await db.execute(batch_ids_q)).scalars().all()
        if not batch_ids:
            break

        try:
            result = await db.execute(
                delete(BlockEmbedding).where(
                    BlockEmbedding.block_id.in_(batch_ids)
                )
            )
            deleted = result.rowcount
            stats["embeddings_deleted"] += deleted
            await db.flush()
            logger.info(
                "[Phase 1] memvault: deleted %d embeddings "
                "(batch offset=%d)",
                deleted, offset,
            )
        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "[Phase 1] memvault batch error at offset %d: %s",
                offset, e,
            )

        offset += LIFECYCLE_BATCH_SIZE

    return stats


async def warm_intelflow_reports(
    db: AsyncSession,
    cutoff: datetime,
    dry_run: bool,
) -> dict:
    """Phase 1: Delete embedding sub-table entries for old reports.

    Rows stay in the main reports table; only the HNSW-indexed
    embedding vectors in report_embeddings are removed.
    """
    from src.modules.intelflow.models import (
        Report,
        ReportEmbedding,
    )

    stats = {"scanned": 0, "embeddings_deleted": 0, "errors": 0}

    old_ids_q = select(Report.id).where(
        Report.created_at < str(cutoff)
    )
    count_q = (
        select(func.count())
        .select_from(ReportEmbedding)
        .where(ReportEmbedding.report_id.in_(old_ids_q))
    )
    total = (await db.execute(count_q)).scalar() or 0
    stats["scanned"] = total

    if total == 0:
        logger.info("[Phase 1] intelflow: no embeddings to warm")
        return stats

    if dry_run:
        logger.info(
            "[DRY-RUN] [Phase 1] Would delete %d report embeddings",
            total,
        )
        stats["embeddings_deleted"] = total
        return stats

    # Batched delete
    offset = 0
    while True:
        batch_ids_q = (
            select(Report.id)
            .where(Report.created_at < str(cutoff))
            .limit(LIFECYCLE_BATCH_SIZE)
            .offset(offset)
        )
        batch_ids = (await db.execute(batch_ids_q)).scalars().all()
        if not batch_ids:
            break

        try:
            result = await db.execute(
                delete(ReportEmbedding).where(
                    ReportEmbedding.report_id.in_(batch_ids)
                )
            )
            deleted = result.rowcount
            stats["embeddings_deleted"] += deleted
            await db.flush()
            logger.info(
                "[Phase 1] intelflow: deleted %d embeddings "
                "(batch offset=%d)",
                deleted, offset,
            )
        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "[Phase 1] intelflow batch error at offset %d: %s",
                offset, e,
            )

        offset += LIFECYCLE_BATCH_SIZE

    return stats


# ============= Phase 2: Warm -> Cold (archive rows) =================


async def archive_memvault_blocks(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 2: Archive old memvault blocks to archive table."""
    from src.modules.memvault.models import (
        BlockArchive,
        BlockEmbedding,
        MemoryBlock,
    )

    stats = {
        "scanned": 0, "cold_archive": 0,
        "cold_blob": 0, "skipped": 0, "errors": 0,
    }

    q = select(MemoryBlock).where(
        MemoryBlock.created_at < str(cutoff)
    )
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    batch_count = 0
    for block in rows:
        try:
            content = block.content or ""
            content_size = len(content.encode("utf-8"))
            archive_type = (
                "cold-blob"
                if content_size > blob_threshold
                else "cold-archive"
            )
            now_str = datetime.now(UTC).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive block %s "
                    "(%s, %d bytes)",
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
                    logger.warning(
                        "S3 upload failed for block %s, "
                        "falling back to cold-archive",
                        block.id,
                    )
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
                delete(BlockEmbedding).where(
                    BlockEmbedding.block_id == block.id
                )
            )

            # Delete original row
            await db.execute(
                delete(MemoryBlock).where(
                    MemoryBlock.id == block.id
                )
            )

            stats[archive_type.replace("-", "_")] += 1
            logger.info(
                "Archived block %s -> %s", block.id, archive_type
            )

            # Batch commit
            batch_count += 1
            if batch_count % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()
                logger.info(
                    "[Phase 2] memvault: flushed batch "
                    "(%d rows so far)",
                    batch_count,
                )

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to archive block %s: %s", block.id, e
            )

    return stats


async def archive_intelflow_reports(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 2: Archive old intelflow reports."""
    from src.modules.intelflow.models import (
        Report,
        ReportArchive,
        ReportEmbedding,
    )

    stats = {
        "scanned": 0, "cold_archive": 0,
        "cold_blob": 0, "skipped": 0, "errors": 0,
    }

    q = select(Report).where(Report.created_at < str(cutoff))
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    batch_count = 0
    for report in rows:
        try:
            content = report.content or ""
            content_size = len(content.encode("utf-8"))
            archive_type = (
                "cold-blob"
                if content_size > blob_threshold
                else "cold-archive"
            )
            now_str = datetime.now(UTC).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive report %s '%s' "
                    "(%s, %d bytes)",
                    report.id, report.title[:40],
                    archive_type, content_size,
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
                    logger.warning(
                        "S3 upload failed for report %s, "
                        "falling back to cold-archive",
                        report.id,
                    )
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
                delete(ReportEmbedding).where(
                    ReportEmbedding.report_id == report.id
                )
            )

            # Delete original row
            await db.execute(
                delete(Report).where(Report.id == report.id)
            )

            stats[archive_type.replace("-", "_")] += 1
            logger.info(
                "Archived report %s -> %s",
                report.id, archive_type,
            )

            batch_count += 1
            if batch_count % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()
                logger.info(
                    "[Phase 2] intelflow reports: flushed batch "
                    "(%d rows so far)",
                    batch_count,
                )

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to archive report %s: %s", report.id, e
            )

    return stats


async def archive_intelflow_briefings(
    db: AsyncSession,
    cutoff: datetime,
    blob_threshold: int,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 2: Archive old intelflow briefings."""
    import json

    from src.modules.intelflow.models import (
        Briefing,
        BriefingArchive,
    )

    stats = {
        "scanned": 0, "cold_archive": 0,
        "cold_blob": 0, "skipped": 0, "errors": 0,
    }

    q = select(Briefing).where(Briefing.created_at < str(cutoff))
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    batch_count = 0
    for briefing in rows:
        try:
            raw_size = len(
                json.dumps(briefing.raw_data or {}).encode("utf-8")
            )
            analyses_size = len(
                json.dumps(briefing.analyses or {}).encode("utf-8")
            )
            debate_size = len(
                (briefing.debate or "").encode("utf-8")
            )
            total_size = raw_size + analyses_size + debate_size
            archive_type = (
                "cold-blob"
                if total_size > blob_threshold
                else "cold-archive"
            )
            now_str = datetime.now(UTC).isoformat()

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would archive briefing %s "
                    "date=%s domain=%s (%s, %d bytes)",
                    briefing.id, briefing.date,
                    briefing.domain, archive_type, total_size,
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
            logger.info(
                "Archived briefing %s -> %s",
                briefing.id, archive_type,
            )

            batch_count += 1
            if batch_count % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()
                logger.info(
                    "[Phase 2] intelflow briefings: flushed batch "
                    "(%d rows so far)",
                    batch_count,
                )

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to archive briefing %s: %s",
                briefing.id, e,
            )

    return stats


# ============= Phase 3: Cold -> Frozen (S3 + frozen table) ==========


async def freeze_memvault_blocks(
    db: AsyncSession,
    cutoff: datetime,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 3: Freeze old archive rows to S3 + frozen table.

    Uploads full snapshot as zstd-compressed JSON to the frozen
    bucket, inserts minimal metadata into blocks_frozen, then
    deletes the archive row (and its cold-blob S3 object if any).
    """
    import json

    from src.modules.memvault.models import (
        BlockArchive,
        BlockFrozen,
    )
    from src.shared.storage import (
        compute_content_hash,
        delete_blob,
        parse_s3_ref,
        resolve_content,
        upload_blob_compressed,
    )

    stats = {"scanned": 0, "frozen": 0, "errors": 0}

    q = select(BlockArchive).where(
        BlockArchive.archived_at < str(cutoff)
    )
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    if len(rows) == 0:
        logger.info(
            "[Phase 3] memvault: no archive rows to freeze"
        )
        return stats

    for i, row in enumerate(rows):
        try:
            if dry_run:
                logger.info(
                    "[DRY-RUN] Would freeze block %s", row.id,
                )
                stats["frozen"] += 1
                continue

            # 1. Resolve content (may be s3:// ref for cold-blob)
            content = row.content
            if content and content.startswith("s3://"):
                content = await resolve_content(content) or ""

            # 2. Build full snapshot JSON
            snapshot = json.dumps({
                "id": row.id,
                "space_id": row.space_id,
                "created_by": row.created_by,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "content": content,
                "block_type": row.block_type,
                "tags": row.tags or [],
                "source_session": row.source_session,
                "confidence": row.confidence,
                "archived_at": row.archived_at,
                "archive_type": row.archive_type,
                "schema_version": 1,
            }, ensure_ascii=False)

            # 3. Compute hash + upload compressed
            content_hash = compute_content_hash(snapshot)
            created_dt = (
                row.created_at[:10]
                if row.created_at else "unknown"
            )
            yyyy = created_dt[:4]
            mm = created_dt[5:7] or "01"
            s3_key = (
                f"memvault/{yyyy}/{mm}/{row.id}.json.zst"
            )

            s3_uri = await upload_blob_compressed(
                s3_key, snapshot,
            )
            if not s3_uri:
                logger.error(
                    "S3 upload failed for block %s", row.id,
                )
                stats["errors"] += 1
                continue

            # 4. Insert frozen metadata
            now_str = datetime.now(UTC).isoformat()
            db.add(BlockFrozen(
                id=row.id,
                space_id=row.space_id,
                created_by=row.created_by,
                created_at=row.created_at,
                archived_at=row.archived_at,
                frozen_at=now_str,
                block_type=row.block_type,
                tags=row.tags or [],
                source_session=row.source_session,
                summary=None,
                s3_uri=s3_uri,
                content_hash=content_hash,
                content_size=len(
                    snapshot.encode("utf-8")
                ),
            ))

            # 5. Delete from archive table
            await db.execute(
                delete(BlockArchive).where(
                    BlockArchive.id == row.id
                )
            )

            # 6. Delete old cold-blob S3 object if present
            if (
                row.content
                and row.content.startswith("s3://")
            ):
                old_bucket, old_key = parse_s3_ref(
                    row.content,
                )
                await delete_blob(
                    old_key, bucket=old_bucket,
                )

            stats["frozen"] += 1

            # Batch flush
            if (i + 1) % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to freeze block %s: %s",
                row.id, e,
            )

    return stats


async def freeze_intelflow_reports(
    db: AsyncSession,
    cutoff: datetime,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 3: Freeze old archived reports to S3 + frozen table.

    Uploads full snapshot as zstd-compressed JSON to the frozen
    bucket, inserts minimal metadata into reports_frozen, then
    deletes the archive row (and its cold-blob S3 object if any).
    """
    import json

    from src.modules.intelflow.models import (
        ReportArchive,
        ReportFrozen,
    )
    from src.shared.storage import (
        compute_content_hash,
        delete_blob,
        parse_s3_ref,
        resolve_content,
        upload_blob_compressed,
    )

    stats = {"scanned": 0, "frozen": 0, "errors": 0}

    q = select(ReportArchive).where(
        ReportArchive.archived_at < str(cutoff)
    )
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    if len(rows) == 0:
        logger.info(
            "[Phase 3] intelflow reports: "
            "no archive rows to freeze"
        )
        return stats

    for i, row in enumerate(rows):
        try:
            if dry_run:
                logger.info(
                    "[DRY-RUN] Would freeze report %s",
                    row.id,
                )
                stats["frozen"] += 1
                continue

            # 1. Resolve content (may be s3:// ref)
            content = row.content
            if content and content.startswith("s3://"):
                content = await resolve_content(content) or ""

            # 2. Build full snapshot JSON
            snapshot = json.dumps({
                "id": row.id,
                "space_id": row.space_id,
                "created_by": row.created_by,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "title": row.title,
                "query": row.query,
                "content": content,
                "sources": row.sources,
                "tags": row.tags or [],
                "skill_name": row.skill_name,
                "archived_at": row.archived_at,
                "archive_type": row.archive_type,
                "schema_version": 1,
            }, ensure_ascii=False)

            # 3. Compute hash + upload compressed
            content_hash = compute_content_hash(snapshot)
            created_dt = (
                row.created_at[:10]
                if row.created_at else "unknown"
            )
            yyyy = created_dt[:4]
            mm = created_dt[5:7] or "01"
            s3_key = (
                f"intelflow/reports/{yyyy}/{mm}"
                f"/{row.id}.json.zst"
            )

            s3_uri = await upload_blob_compressed(
                s3_key, snapshot,
            )
            if not s3_uri:
                logger.error(
                    "S3 upload failed for report %s",
                    row.id,
                )
                stats["errors"] += 1
                continue

            # 4. Insert frozen metadata
            now_str = datetime.now(UTC).isoformat()
            db.add(ReportFrozen(
                id=row.id,
                space_id=row.space_id,
                created_by=row.created_by,
                created_at=row.created_at,
                archived_at=row.archived_at,
                frozen_at=now_str,
                title=row.title,
                query=row.query,
                tags=row.tags or [],
                skill_name=row.skill_name,
                summary=None,
                s3_uri=s3_uri,
                content_hash=content_hash,
                content_size=len(
                    snapshot.encode("utf-8")
                ),
            ))

            # 5. Delete from archive table
            await db.execute(
                delete(ReportArchive).where(
                    ReportArchive.id == row.id
                )
            )

            # 6. Delete old cold-blob S3 object if present
            if (
                row.content
                and row.content.startswith("s3://")
            ):
                old_bucket, old_key = parse_s3_ref(
                    row.content,
                )
                await delete_blob(
                    old_key, bucket=old_bucket,
                )

            stats["frozen"] += 1

            # Batch flush
            if (i + 1) % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to freeze report %s: %s",
                row.id, e,
            )

    return stats


async def freeze_intelflow_briefings(
    db: AsyncSession,
    cutoff: datetime,
    dry_run: bool,
    s3_upload_fn=None,
) -> dict:
    """Phase 3: Freeze old archived briefings to S3 + frozen table.

    Uploads full snapshot as zstd-compressed JSON to the frozen
    bucket, inserts minimal metadata into briefings_frozen, then
    deletes the archive row.
    """
    import json

    from src.modules.intelflow.models import (
        BriefingArchive,
        BriefingFrozen,
    )
    from src.shared.storage import (
        compute_content_hash,
        upload_blob_compressed,
    )

    stats = {"scanned": 0, "frozen": 0, "errors": 0}

    q = select(BriefingArchive).where(
        BriefingArchive.archived_at < str(cutoff)
    )
    rows = (await db.execute(q)).scalars().all()
    stats["scanned"] = len(rows)

    if len(rows) == 0:
        logger.info(
            "[Phase 3] intelflow briefings: "
            "no archive rows to freeze"
        )
        return stats

    for i, row in enumerate(rows):
        try:
            if dry_run:
                logger.info(
                    "[DRY-RUN] Would freeze briefing %s",
                    row.id,
                )
                stats["frozen"] += 1
                continue

            # 1. Build full snapshot JSON
            snapshot = json.dumps({
                "id": row.id,
                "space_id": row.space_id,
                "created_by": row.created_by,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "date": str(row.date),
                "domain": row.domain,
                "raw_data": row.raw_data,
                "analyses": row.analyses,
                "debate": row.debate,
                "archived_at": row.archived_at,
                "archive_type": row.archive_type,
                "schema_version": 1,
            }, ensure_ascii=False)

            # 2. Compute hash + upload compressed
            content_hash = compute_content_hash(snapshot)
            created_dt = (
                row.created_at[:10]
                if row.created_at else "unknown"
            )
            yyyy = created_dt[:4]
            mm = created_dt[5:7] or "01"
            s3_key = (
                f"intelflow/briefings/{yyyy}/{mm}"
                f"/{row.id}.json.zst"
            )

            s3_uri = await upload_blob_compressed(
                s3_key, snapshot,
            )
            if not s3_uri:
                logger.error(
                    "S3 upload failed for briefing %s",
                    row.id,
                )
                stats["errors"] += 1
                continue

            # 3. Insert frozen metadata
            now_str = datetime.now(UTC).isoformat()
            db.add(BriefingFrozen(
                id=row.id,
                space_id=row.space_id,
                created_by=row.created_by,
                created_at=row.created_at,
                archived_at=row.archived_at,
                frozen_at=now_str,
                date=row.date,
                domain=row.domain,
                tags=[],
                summary=None,
                s3_uri=s3_uri,
                content_hash=content_hash,
                content_size=len(
                    snapshot.encode("utf-8")
                ),
            ))

            # 4. Delete from archive table
            await db.execute(
                delete(BriefingArchive).where(
                    BriefingArchive.id == row.id
                )
            )

            stats["frozen"] += 1

            # Batch flush
            if (i + 1) % LIFECYCLE_BATCH_SIZE == 0:
                await db.flush()

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                "Failed to freeze briefing %s: %s",
                row.id, e,
            )

    return stats


# ======================== Main ========================


async def run_archiving(
    db_url: str,
    blob_threshold: int,
    dry_run: bool,
    modules: list[str] | None = None,
    phase: str = "all",
) -> dict:
    """Main archiving entry point — runs all lifecycle phases."""
    async_url = db_url.replace(
        "postgresql://", "postgresql+psycopg://"
    )
    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    now = datetime.now(UTC)
    all_modules = modules or ["memvault", "intelflow"]
    run_phases = (
        [1, 2, 3] if phase == "all"
        else [int(phase)]
    )

    # S3 upload function (only for actual execution)
    s3_upload_fn = None
    if not dry_run:
        try:
            from src.shared.storage import ensure_bucket, upload_blob
            bucket_ok = await ensure_bucket()
            if bucket_ok:
                s3_upload_fn = upload_blob
                logger.info(
                    "S3 storage available — "
                    "COLD-BLOB archiving enabled"
                )
            else:
                logger.warning(
                    "S3 bucket unavailable — "
                    "all entries will use COLD-ARCHIVE"
                )
        except Exception as e:
            logger.warning(
                "S3 not available (%s) — "
                "all entries will use COLD-ARCHIVE", e
            )

    results = {}

    async with async_session() as db:
        async with db.begin():
            # Phase 0: Always print lifecycle report
            await print_lifecycle_report(db, all_modules, now)

            # Phase 1: Hot -> Warm (delete embeddings)
            if 1 in run_phases:
                if "memvault" in all_modules:
                    t = get_threshold("memvault")
                    cutoff = now - timedelta(days=t.hot_days)
                    logger.info(
                        "=== Phase 1: Hot->Warm memvault "
                        "(cutoff: %s, hot_days=%d) ===",
                        cutoff.date(), t.hot_days,
                    )
                    results["p1_memvault_embeddings"] = (
                        await warm_memvault_blocks(
                            db, cutoff, dry_run,
                        )
                    )

                if "intelflow" in all_modules:
                    t = get_threshold("intelflow")
                    cutoff = now - timedelta(days=t.hot_days)
                    logger.info(
                        "=== Phase 1: Hot->Warm intelflow "
                        "(cutoff: %s, hot_days=%d) ===",
                        cutoff.date(), t.hot_days,
                    )
                    results["p1_intelflow_embeddings"] = (
                        await warm_intelflow_reports(
                            db, cutoff, dry_run,
                        )
                    )

            # Phase 2: Warm -> Cold (archive rows)
            if 2 in run_phases:
                if "memvault" in all_modules:
                    t = get_threshold("memvault")
                    cutoff = now - timedelta(days=t.warm_days)
                    logger.info(
                        "=== Phase 2: Warm->Cold memvault "
                        "(cutoff: %s, warm_days=%d) ===",
                        cutoff.date(), t.warm_days,
                    )
                    results["p2_memvault_blocks"] = (
                        await archive_memvault_blocks(
                            db, cutoff, blob_threshold,
                            dry_run, s3_upload_fn,
                        )
                    )

                if "intelflow" in all_modules:
                    t = get_threshold("intelflow")
                    cutoff = now - timedelta(days=t.warm_days)
                    logger.info(
                        "=== Phase 2: Warm->Cold intelflow "
                        "reports (cutoff: %s, warm_days=%d) ===",
                        cutoff.date(), t.warm_days,
                    )
                    results["p2_intelflow_reports"] = (
                        await archive_intelflow_reports(
                            db, cutoff, blob_threshold,
                            dry_run, s3_upload_fn,
                        )
                    )

                    logger.info(
                        "=== Phase 2: Warm->Cold intelflow "
                        "briefings (cutoff: %s) ===",
                        cutoff.date(),
                    )
                    results["p2_intelflow_briefings"] = (
                        await archive_intelflow_briefings(
                            db, cutoff, blob_threshold,
                            dry_run, s3_upload_fn,
                        )
                    )

            # Phase 3: Cold -> Frozen
            if 3 in run_phases:
                if "memvault" in all_modules:
                    t = get_threshold("memvault")
                    cutoff = now - timedelta(days=t.cold_days)
                    logger.info(
                        "=== Phase 3: Cold->Frozen memvault "
                        "(cutoff: %s, cold_days=%d) ===",
                        cutoff.date(), t.cold_days,
                    )
                    results["p3_memvault_blocks"] = (
                        await freeze_memvault_blocks(
                            db, cutoff, dry_run, s3_upload_fn,
                        )
                    )

                if "intelflow" in all_modules:
                    t = get_threshold("intelflow")
                    cutoff = now - timedelta(days=t.cold_days)
                    logger.info(
                        "=== Phase 3: Cold->Frozen intelflow "
                        "reports (cutoff: %s, cold_days=%d) ===",
                        cutoff.date(), t.cold_days,
                    )
                    results["p3_intelflow_reports"] = (
                        await freeze_intelflow_reports(
                            db, cutoff, dry_run, s3_upload_fn,
                        )
                    )

                    logger.info(
                        "=== Phase 3: Cold->Frozen intelflow "
                        "briefings (cutoff: %s) ===",
                        cutoff.date(),
                    )
                    results["p3_intelflow_briefings"] = (
                        await freeze_intelflow_briefings(
                            db, cutoff, dry_run, s3_upload_fn,
                        )
                    )

    # REINDEX CONCURRENTLY for partial HNSW indexes
    if not dry_run and (1 in run_phases or 2 in run_phases):
        logger.info("=== REINDEX CONCURRENTLY (HNSW) ===")
        try:
            async with engine.connect() as conn:
                # autocommit required for REINDEX CONCURRENTLY
                await conn.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                if "memvault" in all_modules:
                    await conn.execute(text(
                        "REINDEX INDEX CONCURRENTLY "
                        "memvault.idx_blocks_embedding_recent"
                    ))
                    logger.info(
                        "Reindexed memvault "
                        "idx_blocks_embedding_recent"
                    )
                if "intelflow" in all_modules:
                    await conn.execute(text(
                        "REINDEX INDEX CONCURRENTLY "
                        "intelflow.idx_reports_embedding_recent"
                    ))
                    logger.info(
                        "Reindexed intelflow "
                        "idx_reports_embedding_recent"
                    )
        except Exception as e:
            logger.warning("REINDEX failed (non-fatal): %s", e)

    await engine.dispose()
    return results


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Four-tier data lifecycle: "
            "Hot -> Warm -> Cold -> Frozen"
        ),
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually execute (default is dry-run)",
    )
    parser.add_argument(
        "--phase", type=str, default="all",
        choices=["1", "2", "3", "all"],
        help="Run specific phase (1=Hot->Warm, "
        "2=Warm->Cold, 3=Cold->Frozen, all=all phases)",
    )
    parser.add_argument(
        "--blob-threshold", type=int,
        default=BLOB_THRESHOLD_BYTES,
        help=(
            "Content size (bytes) above which to use "
            f"COLD-BLOB (default: {BLOB_THRESHOLD_BYTES})"
        ),
    )
    parser.add_argument(
        "--module", type=str,
        choices=["memvault", "intelflow"],
        action="append", dest="modules",
        help="Limit to specific module (can repeat)",
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="Database URL (default: from CORE_DB_URL or config)",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    if dry_run:
        logger.info(
            "=== DRY RUN MODE "
            "(use --execute to actually run) ==="
        )
    else:
        logger.info(
            "=== EXECUTE MODE — changes will be committed ==="
        )

    logger.info("Phase(s): %s", args.phase)

    # Print tier config summary
    for mod, t in TIER_THRESHOLDS.items():
        logger.info(
            "Tier config [%s]: hot=%dd, warm=%dd, "
            "cold=%dd, frozen_retention=%dy",
            mod, t.hot_days, t.warm_days,
            t.cold_days, t.frozen_retention_years,
        )

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
        blob_threshold=args.blob_threshold,
        dry_run=dry_run,
        modules=args.modules,
        phase=args.phase,
    ))

    # Print summary
    print("\n" + "=" * 60)
    print("FOUR-TIER LIFECYCLE SUMMARY")
    print("=" * 60)
    total_actions = 0
    total_errors = 0

    for key, stats in results.items():
        print(f"\n{key}:")
        print(f"  Scanned: {stats.get('scanned', 0)}")

        # Phase 1 stats
        if "embeddings_deleted" in stats:
            ed = stats["embeddings_deleted"]
            total_actions += ed
            print(f"  Embeddings deleted: {ed}")

        # Phase 2 stats
        if "cold_archive" in stats:
            ca = stats["cold_archive"]
            cb = stats["cold_blob"]
            total_actions += ca + cb
            print(f"  Cold-Archive: {ca}")
            print(f"  Cold-Blob:    {cb}")

        # Phase 3 stats
        if "frozen" in stats:
            fr = stats["frozen"]
            total_actions += fr
            print(f"  Frozen: {fr}")

        errs = stats.get("errors", 0)
        total_errors += errs
        print(f"  Errors: {errs}")

    print(f"\nTotal actions: {total_actions}")
    print(f"Total errors:  {total_errors}")
    if dry_run:
        print("\n(Dry run -- no changes made)")
    print("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
