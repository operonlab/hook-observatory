#!/usr/bin/env python3
"""One-shot ETL: workshop PG `agent_metrics` schema → SQLite.

Run AFTER `cargo run --release -- migrate` has created the SQLite schema.

Translation rules:
- TIMESTAMPTZ → ISO-8601 string with +00:00 offset
- DATE        → 'YYYY-MM-DD' string
- BOOLEAN     → 0/1
- JSONB       → JSON string (sqlx::types::Json)

Idempotent: clears each SQLite table before inserting (safe for re-runs).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

PG_DSN = "postgresql://joneshong:dev_12345@localhost:5432/workshop"

TABLES = [
    "dispatch_runs",
    "projects",
    "sessions",
    "snapshots",
    "daily_summary",
    "guardian_actions",
]


def to_iso(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.isoformat() + "+00:00"
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def to_jsonstr(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, sort_keys=True)
    return v


def to_int_bool(v):
    if isinstance(v, bool):
        return 1 if v else 0
    return v


def transform_row(table: str, row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, bool):
            out[k] = to_int_bool(v)
        elif isinstance(v, (datetime, date)):
            out[k] = to_iso(v)
        elif isinstance(v, (dict, list)):
            out[k] = to_jsonstr(v)
        else:
            out[k] = v
    return out


def migrate(pg_dsn: str, sqlite_path: str, dry_run: bool = False) -> dict:
    pg = psycopg.connect(
        pg_dsn, options="-c search_path=agent_metrics,public", row_factory=dict_row
    )
    sl = sqlite3.connect(sqlite_path)
    sl.execute("PRAGMA foreign_keys = ON")

    summary: dict[str, dict] = {}

    for table in TABLES:
        with pg.cursor() as cur:
            cur.execute(f"SELECT * FROM agent_metrics.{table}")
            rows = cur.fetchall()

        sl_cur = sl.execute(f"SELECT COUNT(*) FROM {table}")
        sqlite_before = sl_cur.fetchone()[0]

        if not rows:
            summary[table] = {"pg_rows": 0, "sqlite_before": sqlite_before, "inserted": 0}
            continue

        cols = list(rows[0].keys())
        placeholders = ",".join(["?"] * len(cols))
        col_list = ",".join(cols)
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"

        inserted = 0
        if not dry_run:
            sl.execute(f"DELETE FROM {table}")
            for row in rows:
                trow = transform_row(table, row)
                values = [trow[c] for c in cols]
                sl.execute(sql, values)
                inserted += 1
            sl.commit()

        sl_cur = sl.execute(f"SELECT COUNT(*) FROM {table}")
        sqlite_after = sl_cur.fetchone()[0]
        summary[table] = {
            "pg_rows": len(rows),
            "sqlite_before": sqlite_before,
            "sqlite_after": sqlite_after,
            "inserted": inserted,
        }

    pg.close()
    sl.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="ETL workshop PG agent_metrics → SQLite")
    parser.add_argument("--pg", default=PG_DSN, help="PG DSN")
    parser.add_argument(
        "--sqlite",
        default=str(Path(__file__).resolve().parent.parent / "data" / "agent_metrics.sqlite"),
        help="SQLite path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count only, do not write")
    args = parser.parse_args()

    if not Path(args.sqlite).exists():
        print(f"FATAL: SQLite file not found at {args.sqlite}", file=sys.stderr)
        print("Run `cargo run --release -- migrate` first to create the schema.", file=sys.stderr)
        sys.exit(2)

    print(f"PG     → {args.pg}")
    print(f"SQLite → {args.sqlite}")
    print(f"dry-run: {args.dry_run}")
    print()

    summary = migrate(args.pg, args.sqlite, dry_run=args.dry_run)
    width = max(len(t) for t in TABLES)
    for table, info in summary.items():
        print(
            f"  {table:<{width}}  PG={info['pg_rows']:>5}  →  SQLite={info.get('sqlite_after', '?'):>5}  (was {info['sqlite_before']})"
        )

    total_pg = sum(s["pg_rows"] for s in summary.values())
    total_sl = sum(s.get("sqlite_after", 0) for s in summary.values())
    print()
    print(f"TOTAL  PG={total_pg}  SQLite={total_sl}  match={total_pg == total_sl}")


if __name__ == "__main__":
    main()
