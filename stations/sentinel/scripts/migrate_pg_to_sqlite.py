#!/usr/bin/env python3
"""One-shot migration of legacy Python sentinel data from PostgreSQL into the
Rust sentinel-rs SQLite store.

Schema parity is exact (text/varchar columns map 1-to-1, JSONB columns store
raw JSON strings in SQLite). We batch INSERT OR IGNORE so re-runs are safe and
any rows the Rust port already wrote post-cutover are preserved.

Usage:
    ~/.local/bin/python3 scripts/migrate_pg_to_sqlite.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import psycopg

PG_DSN = "postgresql://joneshong@localhost:5432/workshop"
SQLITE_PATH = "/opt/homebrew/var/lib/workshop/sentinel.db"
BATCH = 5000


def migrate_table(
    pg_cur, sqlite_conn, *, table: str, columns: list[str], dry_run: bool
) -> tuple[int, int]:
    cols_sql = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    pg_cur.execute(f"SELECT {cols_sql} FROM sentinel.{table} ORDER BY created_at")
    inserted = 0
    skipped = 0
    batch: list[tuple] = []
    sqlite_cur = sqlite_conn.cursor()
    insert_sql = f"INSERT OR IGNORE INTO {table} ({cols_sql}) VALUES ({placeholders})"
    while True:
        rows = pg_cur.fetchmany(BATCH)
        if not rows:
            break
        # Coerce: PG JSONB → str, datetime-as-text passes through, None passes through.
        prepared = []
        for row in rows:
            prepared.append(tuple(_coerce(v) for v in row))
        if dry_run:
            inserted += len(prepared)
        else:
            sqlite_cur.executemany(insert_sql, prepared)
            inserted += sqlite_cur.rowcount
            skipped += len(prepared) - sqlite_cur.rowcount
            sqlite_conn.commit()
        if len(rows) < BATCH:
            break
    return inserted, skipped


def _coerce(v):
    # psycopg returns dict for jsonb; SQLite wants string.
    if isinstance(v, (dict, list)):
        import json

        return json.dumps(v, ensure_ascii=False)
    return v


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"PG  src: {PG_DSN}")
    print(f"SQLite dst: {SQLITE_PATH}")
    if args.dry_run:
        print("MODE: dry-run (no writes)")

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.execute("PRAGMA journal_mode=WAL")
    sqlite_conn.execute("PRAGMA synchronous=NORMAL")

    with psycopg.connect(PG_DSN) as pg_conn:
        pg_cur = pg_conn.cursor()

        for tbl, cols in [
            (
                "health_checks",
                ["id", "service", "check_type", "status", "response_ms", "detail", "created_at"],
            ),
            (
                "incidents",
                [
                    "id",
                    "service",
                    "status",
                    "severity",
                    "title",
                    "detail",
                    "diagnosis",
                    "repair_result",
                    "created_at",
                    "resolved_at",
                ],
            ),
        ]:
            t0 = time.time()
            ins, skip = migrate_table(
                pg_cur, sqlite_conn, table=tbl, columns=cols, dry_run=args.dry_run
            )
            dt = time.time() - t0
            print(f"  {tbl}: inserted={ins} skipped(dup)={skip} elapsed={dt:.1f}s")

    sqlite_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
