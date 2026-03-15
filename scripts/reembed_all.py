#!/usr/bin/env python3
"""One-time re-embedding: regenerate all vector embeddings using oMLX Qwen3-Embedding-0.6B.

Reads content from each table, sends to embed_worker via subprocess, updates DB.
Also populates dedicated embedding sub-tables (block_embeddings, triple_embeddings, report_embeddings).
"""

import json
import subprocess
import sys
from pathlib import Path

WORKER = Path.home() / ".venvs" / "omlx" / "embed_worker.py"
PYTHON = Path.home() / ".venvs" / "omlx" / "bin" / "python3"
DB_URL = "postgresql+psycopg://joneshong:REDACTED@localhost/workshop"
BATCH_SIZE = 50  # texts per worker request
EMBEDDING_DIM = 1024


def start_worker():
    proc = subprocess.Popen(
        [str(PYTHON), str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    line = proc.stdout.readline().strip()
    status = json.loads(line)
    if status.get("status") != "ready":
        print(f"Worker failed to start: {status}", file=sys.stderr)
        sys.exit(1)
    print(f"Worker ready: {status.get('model')}")
    return proc


def embed_batch(proc, texts):
    """Send batch of texts to worker, return embeddings."""
    request = json.dumps({"texts": texts}) + "\n"
    proc.stdin.write(request)
    proc.stdin.flush()
    response = proc.stdout.readline().strip()
    try:
        result = json.loads(response)
    except json.JSONDecodeError as e:
        print(f"  Worker response parse error: {e}", file=sys.stderr)
        return [None] * len(texts)
    if "error" in result:
        print(f"  Worker error: {result['error']}", file=sys.stderr)
        return [None] * len(texts)
    return result.get("embeddings", [])


def main():
    from sqlalchemy import create_engine, text

    engine = create_engine(DB_URL)
    proc = start_worker()

    tasks = [
        # (schema, table, id_col, text_expr_sql, sub_table, sub_id_col)
        ("memvault", "blocks", "id", "content", "block_embeddings", "block_id"),
        (
            "memvault",
            "triples",
            "id",
            "subject || ' ' || predicate || ' ' || object",
            "triple_embeddings",
            "triple_id",
        ),
        ("memvault", "attitude_facts", "id", "fact", None, None),
        (
            "intelflow",
            "reports",
            "id",
            "COALESCE(title, '') || ' ' || COALESCE(query, '')",
            "report_embeddings",
            "report_id",
        ),
        (
            "intelflow",
            "topics",
            "id",
            "COALESCE(name, '') || ' ' || COALESCE(description, '')",
            None,
            None,
        ),
        (
            "briefing",
            "briefings",
            "id",
            "COALESCE(title, '') || ' ' || COALESCE(summary, '')",
            None,
            None,
        ),
        (
            "briefing",
            "briefing_entries",
            "id",
            "COALESCE(title, '') || ' ' || COALESCE(content, '')",
            None,
            None,
        ),
    ]

    total_embedded = 0

    with engine.connect() as conn:
        for schema, table, id_col, text_sql, sub_table, sub_id_col in tasks:
            # Fetch rows
            rows = conn.execute(
                text(
                    f"SELECT {id_col}, ({text_sql}) as embed_text FROM {schema}.{table} ORDER BY {id_col}"
                )
            ).fetchall()

            if not rows:
                print(f"  {schema}.{table}: 0 rows, skipping")
                continue

            print(f"  {schema}.{table}: {len(rows)} rows to embed...", end="", flush=True)
            embedded = 0

            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                texts = [r[1] or "" for r in batch]
                ids = [r[0] for r in batch]

                embeddings = embed_batch(proc, texts)

                for row_id, emb in zip(ids, embeddings):
                    if emb and len(emb) == EMBEDDING_DIM:
                        # Update main table
                        conn.execute(
                            text(
                                f"UPDATE {schema}.{table} SET embedding = :emb WHERE {id_col} = :id"
                            ),
                            {"emb": str(emb), "id": row_id},
                        )
                        # Insert into sub-table if applicable
                        if sub_table:
                            conn.execute(
                                text(
                                    f"INSERT INTO {schema}.{sub_table} ({sub_id_col}, embedding) "
                                    f"VALUES (:id, :emb) ON CONFLICT ({sub_id_col}) DO UPDATE SET embedding = :emb"
                                ),
                                {"id": row_id, "emb": str(emb)},
                            )
                        embedded += 1

                conn.commit()

            print(f" {embedded}/{len(rows)} done")
            total_embedded += embedded

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("Warning: worker did not exit within 10s, killing.", file=sys.stderr)
        proc.kill()
    print(f"\n=== Total: {total_embedded} embeddings generated ===")


if __name__ == "__main__":
    main()
