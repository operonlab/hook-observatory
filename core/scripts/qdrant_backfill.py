#!/usr/bin/env python3
"""Backfill Qdrant index from existing PostgreSQL data.

Usage: ~/.local/bin/python3 core/scripts/qdrant_backfill.py [--module MODULE] [--space-id SPACE_ID]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.events.handlers.index_registry import REGISTRY
from src.shared.qdrant_client import is_available
from src.shared.qdrant_search import index_documents_batch, init_collection
from src.shared.search_types import IndexDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def backfill_module(module_name: str, space_id: str | None = None) -> dict:
    """Backfill a single module's data to Qdrant.

    Since we can't easily import all module services without the full app context,
    this uses raw SQL queries via the shared database config.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from src.config import settings

    mapping = REGISTRY.get(module_name)
    if not mapping:
        logger.warning("No mapping found for module: %s", module_name)
        return {"module": module_name, "status": "skipped", "reason": "no mapping"}

    # Convert sync URL to async (postgresql:// → postgresql+psycopg://)
    db_url = settings.db_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(db_url)
    stats = {"module": module_name, "entities": {}}

    async with AsyncSession(engine) as session:
        for entity_name, entity_mapping in mapping.entities.items():
            # Build table name from module convention: {module}.{entity_plural}
            # Map entity types to table names
            table_map = {
                ("intelflow", "report"): "intelflow.reports",
                ("intelflow", "topic"): "intelflow.topics",
                ("taskflow", "task"): "taskflow.tasks",
                ("capture", "capture"): "shared.captures",
                ("finance", "transaction"): "finance.transactions",
                ("finance", "subscription"): "finance.subscriptions",
                ("dailyos", "plan"): "dailyos.daily_plans",
                ("dailyos", "method"): "dailyos.methods",
                ("nodeflow", "flow"): "nodeflow.flows",
                ("invest", "position"): "invest.positions",
                ("invest", "trade"): "invest.trades",
                ("memvault", "memory"): "memvault.blocks",
            }

            table_name = table_map.get((module_name, entity_name))
            if not table_name:
                logger.warning("No table mapping for %s.%s", module_name, entity_name)
                continue

            # Get all content fields + id + space_id
            all_fields = ["id", "space_id", *entity_mapping.content_fields]
            if entity_mapping.tag_field:
                all_fields.append(entity_mapping.tag_field)
            all_fields.extend(entity_mapping.metadata_fields)
            # Add timestamp fields if they exist
            all_fields.extend(["created_at", "updated_at"])
            # Deduplicate
            all_fields = list(dict.fromkeys(all_fields))

            # Check which columns actually exist
            try:
                col_check = await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema || '.' || table_name = :table"
                    ),
                    {"table": table_name},
                )
                existing_cols = {row[0] for row in col_check.fetchall()}
                select_fields = [f for f in all_fields if f in existing_cols]
            except Exception as e:
                logger.warning("Could not check columns for %s: %s", table_name, e)
                select_fields = all_fields

            # Build query
            where_clause = ""
            params = {}
            if space_id:
                where_clause = " WHERE space_id = :space_id"
                params["space_id"] = space_id

            # Check for soft delete
            if "deleted_at" in existing_cols:
                where_clause += (" AND" if where_clause else " WHERE") + " deleted_at IS NULL"

            fields_sql = ", ".join(select_fields)
            query = f"SELECT {fields_sql} FROM {table_name}{where_clause}"  # noqa: S608

            try:
                result = await session.execute(text(query), params)
                rows = result.mappings().all()
            except Exception as e:
                logger.error("Failed to query %s: %s", table_name, e)
                stats["entities"][entity_name] = {"error": str(e)}
                continue

            # Build IndexDocuments
            docs = []
            for row in rows:
                row_dict = dict(row)
                content_parts = []
                for field in entity_mapping.content_fields:
                    val = row_dict.get(field)
                    if val and isinstance(val, str):
                        content_parts.append(val)

                content = "\n".join(content_parts)
                if not content.strip():
                    continue

                tags = []
                if entity_mapping.tag_field and entity_mapping.tag_field in row_dict:
                    raw_tags = row_dict[entity_mapping.tag_field]
                    if isinstance(raw_tags, list):
                        tags = [str(t) for t in raw_tags]

                metadata = {}
                for mf in entity_mapping.metadata_fields:
                    if mf in row_dict and row_dict[mf] is not None:
                        val = row_dict[mf]
                        metadata[mf] = (
                            str(val) if not isinstance(val, (str, int, float, bool)) else val
                        )

                docs.append(IndexDocument(
                    service_id=module_name,
                    entity_id=str(row_dict["id"]),
                    entity_type=entity_mapping.entity_type,
                    space_id=str(row_dict.get("space_id", "")),
                    content=content,
                    tags=tags,
                    created_at=row_dict.get("created_at"),
                    updated_at=row_dict.get("updated_at"),
                    metadata=metadata,
                ))

            # Batch index
            if docs:
                indexed = await index_documents_batch(docs)
                logger.info(
                    "Indexed %d/%d %s.%s documents",
                    indexed, len(docs), module_name, entity_name,
                )
                stats["entities"][entity_name] = {"total": len(docs), "indexed": indexed}
            else:
                logger.info("No documents to index for %s.%s", module_name, entity_name)
                stats["entities"][entity_name] = {"total": 0, "indexed": 0}

    await engine.dispose()
    return stats


async def main():
    parser = argparse.ArgumentParser(description="Backfill Qdrant index from PostgreSQL")
    parser.add_argument("--module", help="Only backfill this module (default: all)")
    parser.add_argument("--space-id", help="Only backfill this space (default: all)")
    args = parser.parse_args()

    if not await is_available():
        logger.error("Qdrant is not available. Start Qdrant first.")
        sys.exit(1)

    # Initialize collection
    ok = await init_collection()
    if not ok:
        logger.error("Failed to initialize Qdrant collection")
        sys.exit(1)

    modules = [args.module] if args.module else list(REGISTRY.keys())

    all_stats = []
    for module_name in modules:
        logger.info("=== Backfilling %s ===", module_name)
        stats = await backfill_module(module_name, args.space_id)
        all_stats.append(stats)

    # Summary
    logger.info("\n=== Backfill Summary ===")
    total_indexed = 0
    total_docs = 0
    for stats in all_stats:
        module = stats["module"]
        for entity, entity_stats in stats.get("entities", {}).items():
            if isinstance(entity_stats, dict) and "indexed" in entity_stats:
                total_indexed += entity_stats["indexed"]
                total_docs += entity_stats["total"]
                logger.info(
                    "  %s.%s: %d/%d indexed",
                    module, entity, entity_stats["indexed"], entity_stats["total"],
                )
    logger.info("Total: %d/%d documents indexed", total_indexed, total_docs)


if __name__ == "__main__":
    asyncio.run(main())
