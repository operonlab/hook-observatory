#!/usr/bin/env python3
"""Migrate auto_survey schema data from PostgreSQL → SQLite.

Usage:
    python3 migrate_pg_to_sqlite.py [--dry-run] [--sqlite-path PATH]

Reads from:  postgresql://joneshong:dev_12345@localhost/workshop  (schema: auto_survey)
Writes to:   stations/auto-survey/data/auto_survey.db  (default)

Prints a migration summary with per-table counts and checksums (MD5 of sorted id list).
Exits 1 if SQLite count != PG count for any table.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Try importing psycopg2; give a clear error if not present.
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PG_DSN = os.environ.get(
    "AUTO_SURVEY_PG_DSN",
    "postgresql://joneshong:dev_12345@localhost/workshop",
)
PG_SCHEMA = "auto_survey"

STATION_ROOT = Path(__file__).resolve().parent.parent  # stations/auto-survey/
DEFAULT_SQLITE_PATH = str(STATION_ROOT / "data" / "auto_survey.db")

MIGRATION_FILE = STATION_ROOT / "migrations" / "20260419000001_init.sql"

TABLES = ["surveys", "questions", "people", "submissions", "daily_runs"]

# ---------------------------------------------------------------------------
# Type conversion helpers
# ---------------------------------------------------------------------------


def _to_text_uuid(v) -> str | None:
    """UUID object or str → 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' lowercase."""
    if v is None:
        return None
    return str(v).lower()


def _to_json_text(v) -> str | None:
    """JSONB dict/list → JSON string; None → None."""
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _to_iso8601(v) -> str | None:
    """datetime/date → ISO-8601 string."""
    if v is None:
        return None
    if isinstance(v, datetime):
        # Ensure UTC offset is present
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _to_int_bool(v) -> int | None:
    """bool/int → 0/1; None → None."""
    if v is None:
        return None
    return 1 if v else 0


# ---------------------------------------------------------------------------
# Per-table row converters
# ---------------------------------------------------------------------------


def _convert_surveys(row: dict) -> dict:
    return {
        "id": _to_text_uuid(row["id"]),
        "url": row["url"],
        "url_hash": row["url_hash"],
        "title": row["title"],
        "type": row["type"],
        "raw_content": row["raw_content"],
        "company_options": _to_json_text(row["company_options"]),
        "created_at": _to_iso8601(row["created_at"]),
    }


def _convert_questions(row: dict) -> dict:
    return {
        "id": _to_text_uuid(row["id"]),
        "survey_id": _to_text_uuid(row["survey_id"]),
        "subject_id": row["subject_id"],
        "question_text": row["question_text"],
        "options": _to_json_text(row["options"]),
        "correct_answer": row["correct_answer"],
        "verified": _to_int_bool(row["verified"]),
        "created_at": _to_iso8601(row["created_at"]),
    }


def _convert_people(row: dict) -> dict:
    return {
        "id": _to_text_uuid(row["id"]),
        "name": row["name"],
        "email": row["email"],
        "company": row["company"],
        "active": _to_int_bool(row["active"]),
        "created_at": _to_iso8601(row["created_at"]),
    }


def _convert_submissions(row: dict) -> dict:
    # is_pathfinder and answers_snapshot may not exist in PG if migration was partial
    return {
        "id": _to_text_uuid(row["id"]),
        "survey_id": _to_text_uuid(row["survey_id"]),
        "person_id": _to_text_uuid(row["person_id"]),
        "status": row["status"],
        "score": row.get("score"),
        "is_pathfinder": _to_int_bool(row.get("is_pathfinder", False)),
        "answers_snapshot": _to_json_text(row.get("answers_snapshot")),
        "error_message": row.get("error_message"),
        "submitted_at": _to_iso8601(row.get("submitted_at")),
    }


def _convert_daily_runs(row: dict) -> dict:
    return {
        "id": _to_text_uuid(row["id"]),
        "run_date": _to_iso8601(row["run_date"]),
        "attend_url": row.get("attend_url"),
        "quiz_url": row.get("quiz_url"),
        "status": row.get("status", "pending"),
        "result_summary": row.get("result_summary"),
        "created_at": _to_iso8601(row.get("created_at")),
        "updated_at": _to_iso8601(row.get("updated_at")),
    }


CONVERTERS = {
    "surveys": _convert_surveys,
    "questions": _convert_questions,
    "people": _convert_people,
    "submissions": _convert_submissions,
    "daily_runs": _convert_daily_runs,
}

# INSERT templates (all columns explicit to protect against future schema drift)
INSERTS = {
    "surveys": """
        INSERT OR IGNORE INTO surveys
            (id, url, url_hash, title, type, raw_content, company_options, created_at)
        VALUES
            (:id, :url, :url_hash, :title, :type, :raw_content, :company_options, :created_at)
    """,
    "questions": """
        INSERT OR IGNORE INTO questions
            (id, survey_id, subject_id, question_text, options, correct_answer, verified, created_at)
        VALUES
            (:id, :survey_id, :subject_id, :question_text, :options, :correct_answer, :verified, :created_at)
    """,
    "people": """
        INSERT OR IGNORE INTO people
            (id, name, email, company, active, created_at)
        VALUES
            (:id, :name, :email, :company, :active, :created_at)
    """,
    "submissions": """
        INSERT OR IGNORE INTO submissions
            (id, survey_id, person_id, status, score, is_pathfinder, answers_snapshot,
             error_message, submitted_at)
        VALUES
            (:id, :survey_id, :person_id, :status, :score, :is_pathfinder,
             :answers_snapshot, :error_message, :submitted_at)
    """,
    "daily_runs": """
        INSERT OR IGNORE INTO daily_runs
            (id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at)
        VALUES
            (:id, :run_date, :attend_url, :quiz_url, :status, :result_summary, :created_at, :updated_at)
    """,
}


# ---------------------------------------------------------------------------
# Checksum helper
# ---------------------------------------------------------------------------


def _checksum(ids: list[str]) -> str:
    """MD5 of sorted id list."""
    joined = ",".join(sorted(ids))
    return hashlib.md5(joined.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# PG helpers
# ---------------------------------------------------------------------------


def _pg_fetch_all(cur, table: str) -> list[dict]:
    """Fetch all rows; gracefully handle missing columns (is_pathfinder / answers_snapshot)."""
    # First, discover actual columns in PG to avoid SELECT * mismatch
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (PG_SCHEMA, table),
    )
    pg_cols = [r[0] for r in cur.fetchall()]

    if not pg_cols:
        # Table doesn't exist in PG → return empty list
        return []

    col_list = ", ".join(f'"{c}"' for c in pg_cols)
    cur.execute(f'SELECT {col_list} FROM {PG_SCHEMA}."{table}"')
    rows = cur.fetchall()
    return [dict(zip(pg_cols, r)) for r in rows]


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------


def run_migration(sqlite_path: str, dry_run: bool) -> bool:
    """Returns True if counts match across all tables."""
    sqlite_path_obj = Path(sqlite_path)
    sqlite_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # -- Read SQLite schema DDL --
    ddl = MIGRATION_FILE.read_text()

    # -- Connect PG --
    print(f"Connecting to PostgreSQL: {PG_DSN}")
    pg_conn = psycopg2.connect(PG_DSN)
    pg_cur = pg_conn.cursor()

    # -- Connect / create SQLite --
    print(f"SQLite target: {sqlite_path}")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_conn.executescript("PRAGMA foreign_keys = OFF;")  # allow bulk load
    sqlite_conn.executescript(ddl)
    sqlite_conn.commit()

    results: dict[str, dict] = {}
    all_ok = True

    for table in TABLES:
        print(f"\n  [{table}] reading from PG...", end="", flush=True)
        pg_rows = _pg_fetch_all(pg_cur, table)
        pg_count = len(pg_rows)
        pg_ids = [str(r["id"]) for r in pg_rows]
        pg_checksum = _checksum(pg_ids)
        print(f" {pg_count} rows (checksum={pg_checksum})")

        if dry_run:
            results[table] = {
                "pg_count": pg_count,
                "sqlite_count": "(dry-run)",
                "checksum": pg_checksum,
                "ok": True,
            }
            continue

        converter = CONVERTERS[table]
        insert_sql = INSERTS[table]

        converted = [converter(r) for r in pg_rows]
        if converted:
            sqlite_conn.executemany(insert_sql, converted)
        sqlite_conn.commit()

        sqlite_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        ok = sqlite_count == pg_count
        if not ok:
            all_ok = False
            print(f"    MISMATCH: PG={pg_count} SQLite={sqlite_count}", file=sys.stderr)

        results[table] = {
            "pg_count": pg_count,
            "sqlite_count": sqlite_count,
            "checksum": pg_checksum,
            "ok": ok,
        }

    sqlite_conn.executescript("PRAGMA foreign_keys = ON;")
    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()

    # -- Summary --
    print("\n" + "=" * 60)
    print(f"{'TABLE':<20} {'PG':>8} {'SQLITE':>8}  {'CHECKSUM':>14}  {'OK':>4}")
    print("-" * 60)
    for table, r in results.items():
        ok_mark = "✓" if r["ok"] else "✗"
        print(
            f"{table:<20} {r['pg_count']:>8} {r['sqlite_count']!s:>8}  "
            f"{r['checksum']:>14}  {ok_mark:>4}"
        )
    print("=" * 60)

    if dry_run:
        print("\n[DRY-RUN] No data written.")
    elif all_ok:
        print("\nMigration COMPLETE — all counts match.")
    else:
        print("\nMigration FAILED — count mismatch detected.", file=sys.stderr)

    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Migrate auto_survey PG → SQLite")
    parser.add_argument(
        "--sqlite-path",
        default=DEFAULT_SQLITE_PATH,
        help=f"Path to SQLite DB (default: {DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read PG and print counts without writing to SQLite",
    )
    args = parser.parse_args()

    ok = run_migration(args.sqlite_path, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
