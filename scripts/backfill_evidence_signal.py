#!/usr/bin/env python3
"""Backfill memvault.triples.evidence_signal from confidence (Phase B).

Migration q1r2s3t4u5v6 加欄位時用 server_default 'extracted'，但對於既有
有 confidence 數值的 triples，應依 confidence 反推三段式：
  extracted (≥0.8) | inferred (0.4-0.8) | ambiguous (<0.4)

無 confidence 的 triples 保留 default 'extracted'（語意：「無從判斷，假設直接」）。

Usage:
    ~/.local/bin/python3 scripts/backfill_evidence_signal.py --dry-run
    ~/.local/bin/python3 scripts/backfill_evidence_signal.py --execute
    ~/.local/bin/python3 scripts/backfill_evidence_signal.py --dry-run --space-id=default

Safety:
- 只更新「目前是 'extracted'（即未被顯式設定者）」的 triple，不覆寫顯式標記
- 使用 transactional UPDATE（PostgreSQL 預設）
- --dry-run 預設，--execute 才真寫
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running this script directly without installing the core package.
WORKSHOP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSHOP_ROOT / "core"))

from sqlalchemy import text  # noqa: E402

# Thresholds — keep in sync with src/modules/memvault/crag_evaluator.py
EXTRACTED_THRESHOLD = 0.8
AMBIGUOUS_THRESHOLD = 0.4


SQL_STATS = """
SELECT
    evidence_signal,
    COUNT(*) AS total,
    COUNT(confidence) AS with_confidence,
    AVG(confidence)::numeric(4,3) AS avg_conf
FROM memvault.triples
GROUP BY evidence_signal
ORDER BY evidence_signal
"""

SQL_PREVIEW = """
SELECT
    CASE
        WHEN confidence IS NULL THEN 'no_change_null_conf'
        WHEN confidence >= :ext THEN 'no_change_already_extracted'
        WHEN confidence >= :amb THEN 'to_inferred'
        ELSE 'to_ambiguous'
    END AS planned_action,
    COUNT(*) AS n
FROM memvault.triples
WHERE evidence_signal = 'extracted'
GROUP BY planned_action
ORDER BY planned_action
"""

SQL_UPDATE_INFERRED = """
UPDATE memvault.triples
SET evidence_signal = 'inferred',
    evidence_method = COALESCE(evidence_method, 'backfill-from-confidence')
WHERE evidence_signal = 'extracted'
  AND confidence IS NOT NULL
  AND confidence >= :amb
  AND confidence < :ext
"""

SQL_UPDATE_AMBIGUOUS = """
UPDATE memvault.triples
SET evidence_signal = 'ambiguous',
    evidence_method = COALESCE(evidence_method, 'backfill-from-confidence')
WHERE evidence_signal = 'extracted'
  AND confidence IS NOT NULL
  AND confidence < :amb
"""


async def run(dry_run: bool, space_id: str | None) -> int:
    from src.shared.database import engine

    async with engine.begin() as conn:
        # 1. Before snapshot
        before = (await conn.execute(text(SQL_STATS))).fetchall()
        print("=== BEFORE ===")
        for row in before:
            print(f"  signal={row[0]:10s} total={row[1]:>6} with_conf={row[2]:>6} avg={row[3]}")

        # 2. Preview planned action
        plan_q = text(SQL_PREVIEW).bindparams(ext=EXTRACTED_THRESHOLD, amb=AMBIGUOUS_THRESHOLD)
        preview = (await conn.execute(plan_q)).fetchall()
        print("\n=== PLANNED ACTIONS ===")
        for row in preview:
            print(f"  {row[0]:35s} n={row[1]:>6}")

        if dry_run:
            print("\n[DRY RUN] No changes applied. Re-run with --execute to apply.")
            return 0

        # 3. Execute updates
        print("\n=== EXECUTING ===")
        inferred_q = text(SQL_UPDATE_INFERRED).bindparams(
            ext=EXTRACTED_THRESHOLD, amb=AMBIGUOUS_THRESHOLD
        )
        ambiguous_q = text(SQL_UPDATE_AMBIGUOUS).bindparams(amb=AMBIGUOUS_THRESHOLD)

        r1 = await conn.execute(inferred_q)
        print(f"  UPDATE → inferred:  {r1.rowcount} rows")
        r2 = await conn.execute(ambiguous_q)
        print(f"  UPDATE → ambiguous: {r2.rowcount} rows")

        # 4. After snapshot
        after = (await conn.execute(text(SQL_STATS))).fetchall()
        print("\n=== AFTER ===")
        for row in after:
            print(f"  signal={row[0]:10s} total={row[1]:>6} with_conf={row[2]:>6} avg={row[3]}")

    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default: preview without writing (set --execute to write)",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Actually apply the UPDATE (off by default for safety)",
    )
    parser.add_argument(
        "--space-id",
        default=None,
        help="Optional filter by space_id (default: all spaces)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(run(dry_run=args.dry_run, space_id=args.space_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
