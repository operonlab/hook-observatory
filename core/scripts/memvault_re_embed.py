"""Memvault re-embed script: re-generate all block embeddings with task-aware prefix.

Usage:
    cd /Users/joneshong/workshop/core
    PYTHONPATH=. /Users/joneshong/workshop/.venv/bin/python scripts/memvault_re_embed.py [--dry-run]

This script:
1. Reads all blocks from memvault.blocks
2. Re-embeds content with 'search_document:' prefix via Ollama
3. Updates both inline embedding (blocks.embedding) and subtable (block_embeddings.embedding)
4. Supports checkpoint for resume on failure
"""

import argparse
import json
import logging
import time
from pathlib import Path

import httpx
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "joneshong",
    "password": "dev_12345",
    "dbname": "workshop",
}
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
BATCH_SIZE = 50
CHECKPOINT_FILE = Path("/tmp/memvault_re_embed_checkpoint.json")


def get_all_blocks(conn):
    """Fetch all block IDs and content."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content, length(content) FROM memvault.blocks "
            "WHERE deleted_at IS NULL ORDER BY created_at"
        )
        return cur.fetchall()


def embed_batch(client: httpx.Client, texts: list[str]) -> list[list[float] | None]:
    """Call Ollama to embed a batch of texts with search_document prefix."""
    prefixed = [f"search_document: {t}" for t in texts]
    try:
        resp = client.post(
            OLLAMA_URL,
            json={"model": MODEL, "input": prefixed},
            timeout=60.0,
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        results = []
        for i in range(len(texts)):
            if i < len(embeddings) and len(embeddings[i]) == EMBEDDING_DIM:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results
    except Exception as e:
        logger.error("Embedding batch failed: %s", e)
        return [None] * len(texts)


def update_embeddings(conn, block_ids: list[str], embeddings: list[list[float]]):
    """Update both inline and subtable embeddings."""
    with conn.cursor() as cur:
        for bid, emb in zip(block_ids, embeddings, strict=True):
            if emb is None:
                continue
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            # Update inline embedding
            cur.execute(
                "UPDATE memvault.blocks SET embedding = %s::vector WHERE id = %s",
                (emb_str, bid),
            )
            # Upsert subtable embedding
            cur.execute(
                "INSERT INTO memvault.block_embeddings (block_id, embedding) "
                "VALUES (%s, %s::vector) "
                "ON CONFLICT (block_id) DO UPDATE SET embedding = EXCLUDED.embedding",
                (bid, emb_str),
            )
    conn.commit()


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text()))
    return set()


def save_checkpoint(processed: set[str]):
    CHECKPOINT_FILE.write_text(json.dumps(list(processed)))


def main():
    parser = argparse.ArgumentParser(description="Re-embed memvault blocks with task-aware prefix")
    parser.add_argument("--dry-run", action="store_true", help="Only report, don't update DB")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    client = httpx.Client()

    blocks = get_all_blocks(conn)
    logger.info("Total blocks: %d", len(blocks))

    processed = load_checkpoint()
    pending = [(bid, content, clen) for bid, content, clen in blocks if bid not in processed]
    logger.info("Pending: %d (already processed: %d)", len(pending), len(processed))

    if not pending:
        logger.info("Nothing to do!")
        return

    t0 = time.time()
    success = 0
    failed = 0

    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        batch_ids = [b[0] for b in batch]
        batch_texts = [b[1] for b in batch]

        logger.info(
            "Batch %d/%d (%d blocks)...",
            i // BATCH_SIZE + 1,
            -(-len(pending) // BATCH_SIZE),
            len(batch),
        )

        if args.dry_run:
            logger.info("  [DRY RUN] Would embed %d blocks", len(batch))
            processed.update(batch_ids)
            success += len(batch)
            continue

        embeddings = embed_batch(client, batch_texts)

        ok_ids = []
        ok_embs = []
        for bid, emb in zip(batch_ids, embeddings, strict=True):
            if emb is not None:
                ok_ids.append(bid)
                ok_embs.append(emb)
                success += 1
            else:
                logger.warning("  SKIP %s: embedding failed", bid)
                failed += 1

        if ok_ids:
            update_embeddings(conn, ok_ids, ok_embs)

        processed.update(batch_ids)
        save_checkpoint(processed)

    elapsed = time.time() - t0
    logger.info("Done in %.1fs: %d success, %d failed", elapsed, success, failed)

    # Cleanup checkpoint on success
    if failed == 0 and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleaned up")

    conn.close()
    client.close()


if __name__ == "__main__":
    main()
