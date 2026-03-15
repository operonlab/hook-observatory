"""Memvault re-embed script: re-generate all block embeddings via oMLX bridge.

Usage:
    cd /Users/joneshong/workshop/core
    PYTHONPATH=. /Users/joneshong/workshop/.venv/bin/python scripts/memvault_re_embed.py [--dry-run]

This script:
1. Reads all blocks from memvault.blocks
2. Re-embeds content via oMLX subprocess (Qwen3-Embedding-0.6B, 1024d)
3. Updates both inline embedding (blocks.embedding) and subtable (block_embeddings.embedding)
4. Supports checkpoint for resume on failure
"""

import argparse
import json
import logging
import subprocess
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = "postgresql+psycopg://joneshong:dev_12345@localhost:5432/workshop"
EMBEDDING_DIM = 1024
BATCH_SIZE = 50
CHECKPOINT_FILE = Path("/tmp/memvault_re_embed_checkpoint.json")  # noqa: S108

OMLX_VENV = Path.home() / ".venvs" / "omlx"
WORKER_SCRIPT = OMLX_VENV / "embed_worker.py"
PYTHON = OMLX_VENV / "bin" / "python3"


class OmlxWorker:
    """Manages a persistent oMLX embed worker subprocess."""

    def __init__(self):
        self.proc = None

    def start(self):
        if not PYTHON.exists() or not WORKER_SCRIPT.exists():
            raise RuntimeError(f"oMLX venv not found at {OMLX_VENV}")

        self.proc = subprocess.Popen(  # noqa: S603
            [str(PYTHON), str(WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("oMLX worker produced no output")
        status = json.loads(line.strip())
        if status.get("status") != "ready":
            raise RuntimeError(f"oMLX worker unexpected status: {status}")
        logger.info("oMLX worker ready: %s (dim=%s)", status.get("model"), status.get("dim"))

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        request = json.dumps({"texts": texts, "task_type": "search_document"}) + "\n"
        self.proc.stdin.write(request)
        self.proc.stdin.flush()
        response_line = self.proc.stdout.readline()
        if not response_line:
            logger.error("oMLX worker returned empty response")
            return [None] * len(texts)
        response = json.loads(response_line.strip())
        if "error" in response:
            logger.error("oMLX error: %s", response["error"])
            return [None] * len(texts)
        embeddings = response.get("embeddings", [])
        results = []
        for i in range(len(texts)):
            if i < len(embeddings) and embeddings[i] and len(embeddings[i]) == EMBEDDING_DIM:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results

    def shutdown(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


def get_all_blocks(conn, missing_only: bool = False):
    """Fetch block IDs and content. If missing_only, only blocks without embedding."""
    from sqlalchemy import text

    query = "SELECT id, content, length(content) FROM memvault.blocks WHERE deleted_at IS NULL"
    if missing_only:
        query += " AND embedding IS NULL"
    query += " ORDER BY created_at"
    rows = conn.execute(text(query)).fetchall()
    return rows


def update_embeddings(conn, block_ids: list[str], embeddings: list[list[float]]):
    """Update both inline and subtable embeddings."""
    from sqlalchemy import text

    for bid, emb in zip(block_ids, embeddings, strict=True):
        if emb is None:
            continue
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        conn.execute(
            text("UPDATE memvault.blocks SET embedding = CAST(:emb AS vector) WHERE id = :bid"),
            {"emb": emb_str, "bid": bid},
        )
        conn.execute(
            text(
                "INSERT INTO memvault.block_embeddings (block_id, embedding) "
                "VALUES (:bid, CAST(:emb AS vector)) "
                "ON CONFLICT (block_id) DO UPDATE SET embedding = EXCLUDED.embedding"
            ),
            {"bid": bid, "emb": emb_str},
        )
    conn.commit()


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text()))
    return set()


def save_checkpoint(processed: set[str]):
    CHECKPOINT_FILE.write_text(json.dumps(list(processed)))


def main():
    parser = argparse.ArgumentParser(description="Re-embed memvault blocks via oMLX")
    parser.add_argument("--dry-run", action="store_true", help="Only report, don't update DB")
    parser.add_argument(
        "--missing-only", action="store_true", help="Only re-embed blocks with NULL embedding"
    )
    args = parser.parse_args()

    from sqlalchemy import create_engine

    engine = create_engine(DB_URL)

    worker = OmlxWorker()
    if not args.dry_run:
        worker.start()

    try:
        with engine.connect() as conn:
            blocks = get_all_blocks(conn, missing_only=args.missing_only)
            logger.info(
                "Total blocks: %d%s", len(blocks), " (missing only)" if args.missing_only else ""
            )

            processed = load_checkpoint()
            pending = [
                (bid, content, clen) for bid, content, clen in blocks if bid not in processed
            ]
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

                embeddings = worker.embed_batch(batch_texts)

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

            if failed == 0 and CHECKPOINT_FILE.exists():
                CHECKPOINT_FILE.unlink()
                logger.info("Checkpoint cleaned up")
    finally:
        worker.shutdown()


if __name__ == "__main__":
    main()
