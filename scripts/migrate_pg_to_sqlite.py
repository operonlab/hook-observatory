#!/usr/bin/env python3
"""PG → SQLite 資料遷移：auto_survey 5 張表.

用法：
    python3 scripts/migrate_pg_to_sqlite.py \
        --pg postgresql://joneshong:dev_12345@localhost/workshop \
        --schema auto_survey \
        --sqlite stations/auto-survey-rs/data/auto_survey.db

型別轉換：
    UUID         → TEXT  (str(uuid))
    JSONB        → TEXT  (json.dumps)
    TIMESTAMPTZ  → TEXT  (ISO-8601 含 offset)
    DATE         → TEXT  (YYYY-MM-DD)
    BOOLEAN      → INTEGER (0/1)

驗證：每張表 count 匹配 + MD5 checksum of sorted id list。
若 count 不一致 → exit 1。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime


def _to_text(v):
    """Convert PG value → SQLite TEXT/INTEGER per type table."""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float, str)):
        return v
    if isinstance(v, datetime):
        # ISO-8601 with offset
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    # uuid.UUID, decimal, etc.
    return str(v)


def _checksum(rows: list[tuple]) -> str:
    ids = sorted(str(r[0]) for r in rows)
    return hashlib.md5("\n".join(ids).encode()).hexdigest()[:12]


TABLES = ["surveys", "questions", "people", "submissions", "daily_runs"]

# Column lists (in order of INSERT) — must match SQLite schema
COLS = {
    "surveys": ["id", "url", "url_hash", "title", "type", "raw_content", "company_options", "created_at"],
    "questions": ["id", "survey_id", "subject_id", "question_text", "options", "correct_answer", "verified", "created_at"],
    "people": ["id", "name", "email", "company", "active", "created_at"],
    "submissions": ["id", "survey_id", "person_id", "status", "score", "is_pathfinder", "answers_snapshot", "error_message", "submitted_at"],
    "daily_runs": ["id", "run_date", "attend_url", "quiz_url", "status", "result_summary", "created_at", "updated_at"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg", required=True, help="PostgreSQL URL")
    parser.add_argument("--schema", default="auto_survey")
    parser.add_argument("--sqlite", required=True, help="SQLite file path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        import psycopg  # type: ignore
    except ImportError:
        print("FATAL: psycopg not installed. Run: uv pip install 'psycopg[binary]'", file=sys.stderr)
        return 2

    pg = psycopg.connect(args.pg, autocommit=True)
    sq = sqlite3.connect(args.sqlite)
    sq.execute("PRAGMA foreign_keys = OFF")

    results = []
    try:
        for table in TABLES:
            cols = COLS[table]
            pg_cur = pg.cursor()
            # `is_pathfinder` and `answers_snapshot` may not exist in old PG schema — handle NoneType fall back
            try:
                pg_cur.execute(f'SELECT {", ".join(cols)} FROM {args.schema}.{table}')
                rows = pg_cur.fetchall()
            except psycopg.errors.UndefinedColumn:
                # Retry without the newer columns
                pg.rollback()
                safe_cols = [c for c in cols if c not in ("is_pathfinder", "answers_snapshot")]
                pg_cur.execute(f'SELECT {", ".join(safe_cols)} FROM {args.schema}.{table}')
                partial = pg_cur.fetchall()
                # Fill missing columns with defaults
                rows = []
                for r in partial:
                    d = dict(zip(safe_cols, r))
                    if "is_pathfinder" in cols:
                        d["is_pathfinder"] = False
                    if "answers_snapshot" in cols:
                        d["answers_snapshot"] = None
                    rows.append(tuple(d[c] for c in cols))

            pg_count = len(rows)
            pg_sum = _checksum(rows) if rows else "empty"

            if not args.dry_run:
                sq.execute(f"DELETE FROM {table}")
                placeholders = ", ".join("?" * len(cols))
                sq.executemany(
                    f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({placeholders})',
                    [tuple(_to_text(v) for v in r) for r in rows],
                )
                sq.commit()

                sq_count = sq.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                sq_rows = sq.execute(f"SELECT id FROM {table}").fetchall()
                sq_sum = _checksum(sq_rows) if sq_rows else "empty"
            else:
                sq_count = pg_count
                sq_sum = pg_sum

            ok = (pg_count == sq_count) and (pg_sum == sq_sum)
            results.append((table, pg_count, sq_count, pg_sum, sq_sum, ok))
            mark = "✓" if ok else "✗"
            print(f"  {mark} {table:<15} pg={pg_count:<6} sq={sq_count:<6} sum_pg={pg_sum} sum_sq={sq_sum}")

    finally:
        pg.close()
        sq.close()

    all_ok = all(r[-1] for r in results)
    total_pg = sum(r[1] for r in results)
    total_sq = sum(r[2] for r in results)
    print("\n" + "=" * 60)
    print(f"Totals: pg={total_pg}  sqlite={total_sq}  status={'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
