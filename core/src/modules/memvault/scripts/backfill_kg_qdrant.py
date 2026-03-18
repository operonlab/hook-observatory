"""Backfill KG data (triples, attitudes) into Qdrant.

Run from workshop root:
    cd core && ../.venv/bin/python3 src/modules/memvault/scripts/backfill_kg_qdrant.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve()
_core_root = _here.parents[4]  # .../core
if str(_core_root) not in sys.path:
    sys.path.insert(0, str(_core_root))

for _env_path in [_core_root / ".env", _core_root.parent / ".env"]:
    if _env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(_env_path)
        break

# ---------------------------------------------------------------------------
# Imports (after path bootstrap)
# ---------------------------------------------------------------------------
from sqlalchemy import create_engine, text  # noqa: E402

from src.shared.qdrant_search import index_documents_batch, init_collection  # noqa: E402
from src.shared.search_types import IndexDocument  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_raw_url = os.environ.get(
    "CORE_DB_URL",
    "postgresql://joneshong:REDACTED@localhost/workshop",
)
# Ensure psycopg3 driver (project uses psycopg, not psycopg2)
DATABASE_URL = (
    _raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if "+" not in _raw_url.split("://")[0]
    else _raw_url
)
BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_triple_doc(row) -> IndexDocument:
    return IndexDocument(
        service_id="memvault-triple",
        entity_id=str(row.id),
        entity_type="triple",
        space_id=str(row.space_id),
        content=f"{row.subject} {row.predicate} {row.object}",
        tags=[row.subject, row.predicate],
        created_at=row.created_at if isinstance(row.created_at, datetime) else None,
    )


def _row_to_attitude_doc(row) -> IndexDocument:
    return IndexDocument(
        service_id="memvault-attitude",
        entity_id=str(row.id),
        entity_type="attitude",
        space_id=str(row.space_id),
        content=f"{row.category}: {row.fact}",
        tags=[row.category],
        created_at=row.created_at if isinstance(row.created_at, datetime) else None,
    )


async def _index_in_batches(
    docs: list[IndexDocument],
    label: str,
    batch_size: int = BATCH_SIZE,
) -> int:
    total = len(docs)
    indexed = 0
    for start in range(0, total, batch_size):
        batch = docs[start : start + batch_size]
        count = await index_documents_batch(batch)
        indexed += count
        end = min(start + batch_size, total)
        print(f"  {label}: {end}/{total} processed, {indexed} indexed so far")
    return indexed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=== KG → Qdrant Backfill ===")
    print(f"Database: {DATABASE_URL.split('@')[-1]}")

    # 1. Init Qdrant collection
    print("\n[1/3] Initialising Qdrant collection...")
    ok = await init_collection()
    if not ok:
        print("ERROR: Qdrant unavailable. Aborting.")
        sys.exit(1)
    print("      Collection ready.")

    # 2. Fetch KG records (sync engine — simpler, no asyncpg needed)
    print("\n[2/3] Fetching KG records...")
    engine = create_engine(DATABASE_URL, echo=False)
    with engine.connect() as conn:
        triple_rows = conn.execute(
            text(
                "SELECT id, space_id, subject, predicate, object, created_at"
                " FROM memvault.triples WHERE invalid_at IS NULL ORDER BY created_at"
            )
        ).fetchall()
        attitude_rows = conn.execute(
            text(
                "SELECT id, space_id, category, fact, created_at"
                " FROM memvault.attitude_facts WHERE superseded_by IS NULL ORDER BY created_at"
            )
        ).fetchall()
    engine.dispose()

    print(f"      Found {len(triple_rows)} valid triples")
    print(f"      Found {len(attitude_rows)} active attitudes")

    if not triple_rows and not attitude_rows:
        print("\nNothing to index. Done.")
        return

    triple_docs = [_row_to_triple_doc(r) for r in triple_rows]
    attitude_docs = [_row_to_attitude_doc(r) for r in attitude_rows]

    # 3. Index in batches
    print(f"\n[3/3] Indexing into Qdrant (batch_size={BATCH_SIZE})...")

    t_idx = 0
    a_idx = 0
    if triple_docs:
        print(f"\n  --- Triples ({len(triple_docs)}) ---")
        t_idx = await _index_in_batches(triple_docs, "triples")
    if attitude_docs:
        print(f"\n  --- Attitudes ({len(attitude_docs)}) ---")
        a_idx = await _index_in_batches(attitude_docs, "attitudes")

    # Summary
    total_ok = t_idx + a_idx
    total_all = len(triple_docs) + len(attitude_docs)
    print(f"\n=== Summary: {total_ok}/{total_all} indexed ===")
    if total_ok < total_all:
        print(f"  WARNING: {total_all - total_ok} failed")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
