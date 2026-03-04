"""
Migrate existing briefing JSONB blobs into individual briefing_entries rows.

Converts:
  - raw_data (JSONB dict)  -> entries with phase='raw',      key=domain_name
  - analyses (JSONB dict)  -> entries with phase='analysis',  key=analyst_name
  - debate   (TEXT)         -> entries with phase='debate',    key=analyst_name
                              (parsed by '=== name ===' delimiters)

Embeddings are left NULL for later backfill.
"""

import re
import sys
from datetime import UTC, datetime

import psycopg
from uuid_utils import uuid7

DSN = "postgresql://joneshong:dev_12345@localhost/workshop"
SCHEMA = "intelflow"

DEBATE_DELIM = re.compile(r"^===\s*(.+?)\s*===$")


def parse_debate(text: str) -> dict[str, str]:
    """Parse debate text into {analyst_name: content} sections."""
    if not text or not text.strip():
        return {}

    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        m = DEBATE_DELIM.match(line.strip())
        if m:
            # Save previous section
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def migrate():
    conn = psycopg.connect(DSN)
    try:
        with conn.cursor() as cur:
            # Verify target table is empty
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.briefing_entries")
            existing = cur.fetchone()[0]
            if existing > 0:
                print(
                    f"[ABORT] briefing_entries already has {existing} rows. "
                    "Clear the table first if you want to re-run."
                )
                sys.exit(1)

            # Fetch all briefings
            cur.execute(f"""
                SELECT id, space_id, created_by, created_at,
                       raw_data, analyses, debate
                FROM {SCHEMA}.briefings
                ORDER BY created_at
            """)
            briefings = cur.fetchall()
            print(f"Found {len(briefings)} briefings to migrate.\n")

            total_entries = 0
            stats = {"raw": 0, "analysis": 0, "debate": 0}

            for row in briefings:
                bid, space_id, created_by, created_at, raw_data, analyses, debate = row
                entries = []
                now = datetime.now(UTC)

                # --- Phase: raw ---
                if raw_data and isinstance(raw_data, dict):
                    for domain_name, content in raw_data.items():
                        entries.append(
                            {
                                "id": uuid7().hex,
                                "briefing_id": bid,
                                "phase": "raw",
                                "key": domain_name,
                                "content": str(content) if content else "",
                                "space_id": space_id,
                                "created_by": created_by,
                                "created_at": created_at,
                                "updated_at": now,
                            }
                        )
                        stats["raw"] += 1

                # --- Phase: analysis ---
                if analyses and isinstance(analyses, dict):
                    for analyst_name, content in analyses.items():
                        entries.append(
                            {
                                "id": uuid7().hex,
                                "briefing_id": bid,
                                "phase": "analysis",
                                "key": analyst_name,
                                "content": str(content) if content else "",
                                "space_id": space_id,
                                "created_by": created_by,
                                "created_at": created_at,
                                "updated_at": now,
                            }
                        )
                        stats["analysis"] += 1

                # --- Phase: debate ---
                debate_sections = parse_debate(debate)
                for analyst_name, content in debate_sections.items():
                    entries.append(
                        {
                            "id": uuid7().hex,
                            "briefing_id": bid,
                            "phase": "debate",
                            "key": analyst_name,
                            "content": content,
                            "space_id": space_id,
                            "created_by": created_by,
                            "created_at": created_at,
                            "updated_at": now,
                        }
                    )
                    stats["debate"] += 1

                # Batch insert for this briefing
                if entries:
                    cur.executemany(
                        f"""
                        INSERT INTO {SCHEMA}.briefing_entries
                            (id, briefing_id, phase, key, content,
                             embedding, metadata, space_id, created_by,
                             created_at, updated_at, deleted_at)
                        VALUES
                            (%(id)s, %(briefing_id)s, %(phase)s, %(key)s, %(content)s,
                             NULL, NULL, %(space_id)s, %(created_by)s,
                             %(created_at)s, %(updated_at)s, NULL)
                    """,
                        entries,
                    )

                total_entries += len(entries)
                print(f"  Briefing {bid[:12]}... -> {len(entries)} entries")

            conn.commit()

            # Verify
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.briefing_entries")
            final_count = cur.fetchone()[0]

            print(f"\n{'=' * 50}")
            print("Migration complete!")
            print(f"  Total entries inserted: {total_entries}")
            print(f"  Verified in DB:        {final_count}")
            print("  Breakdown:")
            print(f"    raw:      {stats['raw']}")
            print(f"    analysis: {stats['analysis']}")
            print(f"    debate:   {stats['debate']}")
            print(f"{'=' * 50}")

            if total_entries != final_count:
                print("[WARN] Insert count mismatch!", file=sys.stderr)
                sys.exit(1)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
