#!/usr/bin/env python3
"""Batch re-extraction — run extract.py v2 on all session transcripts.

Usage:
    cd /Users/joneshong/workshop
    PYTHONPATH=core/src ~/.local/bin/python3 mcp/memvault/scripts/re_extract_batch.py [options]

Options:
    --priority P0|P1|P2|ALL  Which sessions to process (default: P0)
    --parallel N             Number of parallel workers (default: 4)
    --dry-run                List sessions without extracting
    --soft-delete            Soft-delete existing blocks before re-extracting
    --limit N                Max sessions to process

Environment:
    MEMVAULT_LLM=gemini              Extraction LLM (default: gemini)
    MEMVAULT_REFINE_LLM=codex        Refinement LLM (default: codex for batch)
    MEMVAULT_REFINE_MODEL=           Refinement model override
    MEMVAULT_REFINE=1                Enable/disable refinement (default: 1)

Priority tiers:
    P0: Sessions that have NEVER been extracted (no blocks in DB)
    P1: Sessions with existing V1 blocks (will soft-delete + re-extract)
    P2: Small sessions (<10KB) that were skipped
    ALL: P0 + P1 (skip P2 as they're too small)
"""

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TRANSCRIPT_DIR = Path.home() / ".claude" / "projects" / "-Users-joneshong"
EXTRACT_SCRIPT = Path(__file__).parent / "extract.py"
PYTHON = str(Path.home() / ".local" / "bin" / "python3")
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "re-extract-batch.log"
DB_URL = "postgresql+psycopg://joneshong:REDACTED@localhost:5432/workshop"
MIN_TRANSCRIPT_SIZE = 10_000  # 10KB minimum for extraction

LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[batch] {ts} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_sessions_with_blocks() -> set[str]:
    """Get session IDs that already have blocks in DB."""
    from sqlalchemy import create_engine, text

    engine = create_engine(DB_URL)
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT DISTINCT source_session FROM memvault.blocks "
                "WHERE deleted_at IS NULL AND source_session IS NOT NULL "
                "AND source_session != ''"
            )
        ).fetchall()
    return {r[0] for r in rows}


def soft_delete_blocks(session_ids: list[str]) -> int:
    """Soft-delete blocks for given session IDs. Returns count deleted."""
    if not session_ids:
        return 0
    from sqlalchemy import create_engine, text

    engine = create_engine(DB_URL)
    total = 0
    with engine.connect() as c:
        for sid in session_ids:
            result = c.execute(
                text(
                    "UPDATE memvault.blocks SET deleted_at = NOW() "
                    "WHERE source_session = :sid AND deleted_at IS NULL"
                ),
                {"sid": sid},
            )
            total += result.rowcount
        c.commit()
    return total


def classify_transcripts(
    exclude_sessions: set[str] | None = None,
) -> dict[str, list[tuple[Path, int]]]:
    """Classify transcripts into priority tiers."""
    existing = get_sessions_with_blocks()
    exclude = exclude_sessions or set()

    tiers = {"P0": [], "P1": [], "P2": []}

    for t in TRANSCRIPT_DIR.glob("*.jsonl"):
        sid = t.stem
        if sid in exclude:
            continue
        size = t.stat().st_size

        if sid in existing:
            if size >= MIN_TRANSCRIPT_SIZE:
                tiers["P1"].append((t, size))
            # Skip small sessions with existing blocks
        else:
            if size >= MIN_TRANSCRIPT_SIZE:
                tiers["P0"].append((t, size))
            else:
                tiers["P2"].append((t, size))

    # Sort each tier by size descending (biggest = most valuable first)
    for tier in tiers.values():
        tier.sort(key=lambda x: x[1], reverse=True)

    return tiers


def run_extraction(transcript: Path, env: dict) -> tuple[str, bool, float]:
    """Run extract.py on a single transcript. Returns (session_id, success, elapsed)."""
    sid = transcript.stem
    cwd = "/Users/joneshong/workshop"

    input_json = json.dumps(
        {
            "session_id": sid,
            "transcript_path": str(transcript),
            "cwd": cwd,
        }
    )

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [PYTHON, str(EXTRACT_SCRIPT)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,  # 10 min per session
        )
        elapsed = time.monotonic() - t0
        success = result.returncode == 0
        if not success:
            log(f"  FAIL {sid}: exit {result.returncode}")
        return sid, success, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        log(f"  TIMEOUT {sid} after {elapsed:.0f}s")
        return sid, False, elapsed
    except Exception as e:
        elapsed = time.monotonic() - t0
        log(f"  ERROR {sid}: {e}")
        return sid, False, elapsed


def main():
    parser = argparse.ArgumentParser(description="Batch re-extraction for memvault")
    parser.add_argument(
        "--priority",
        choices=["P0", "P1", "P2", "ALL"],
        default="P0",
        help="Which priority tier to process",
    )
    parser.add_argument("--parallel", type=int, default=4, help="Parallel workers")
    parser.add_argument("--dry-run", action="store_true", help="List only, don't extract")
    parser.add_argument(
        "--soft-delete",
        action="store_true",
        help="Soft-delete existing blocks before re-extracting P1",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max sessions to process")
    parser.add_argument("--exclude", nargs="*", default=[], help="Session IDs to exclude")
    args = parser.parse_args()

    log("=" * 60)
    log("Memvault batch re-extraction v2")
    log("=" * 60)

    # Auto-exclude: find transcripts modified in last 5 minutes (likely active sessions)
    exclude = set(args.exclude)
    now = time.time()
    for t in TRANSCRIPT_DIR.glob("*.jsonl"):
        if now - t.stat().st_mtime < 300:
            exclude.add(t.stem)
            log(f"Auto-excluding active session: {t.stem}")

    # Classify
    tiers = classify_transcripts(exclude_sessions=exclude)
    for tier_name, sessions in tiers.items():
        total_mb = sum(s for _, s in sessions) / 1024 / 1024
        log(f"{tier_name}: {len(sessions)} sessions ({total_mb:.1f} MB)")

    # Select sessions to process
    if args.priority == "ALL":
        selected = tiers["P0"] + tiers["P1"]
    else:
        selected = tiers[args.priority]

    if args.limit > 0:
        selected = selected[: args.limit]

    if not selected:
        log("No sessions to process.")
        return

    log(f"Selected: {len(selected)} sessions")

    if args.dry_run:
        for t, size in selected[:20]:
            log(f"  {t.stem} ({size // 1024}KB)")
        if len(selected) > 20:
            log(f"  ... and {len(selected) - 20} more")
        return

    # Soft-delete P1 blocks if requested
    if args.soft_delete and args.priority in ("P1", "ALL"):
        p1_sids = [t.stem for t, _ in tiers["P1"]]
        if p1_sids:
            deleted = soft_delete_blocks(p1_sids)
            log(f"Soft-deleted {deleted} existing blocks for {len(p1_sids)} P1 sessions.")

    # Build env for extraction subprocesses
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["MEMVAULT_SKIP_RECALL"] = "1"
    # Default to codex for refinement in batch mode (save Claude quota)
    env.setdefault("MEMVAULT_REFINE_LLM", "codex")
    env.setdefault("MEMVAULT_LLM", "gemini")

    log(
        f"Pipeline: {env.get('MEMVAULT_LLM')} extraction → "
        f"{env.get('MEMVAULT_REFINE_LLM')} refinement"
    )
    log(f"Workers: {args.parallel}")

    # Execute
    t0 = time.monotonic()
    success_count = 0
    fail_count = 0
    total_extract_time = 0.0

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(run_extraction, transcript, env): (transcript, size)
            for transcript, size in selected
        }

        for i, future in enumerate(as_completed(futures), 1):
            transcript, size = futures[future]
            sid, success, elapsed = future.result()
            total_extract_time += elapsed

            if success:
                success_count += 1
            else:
                fail_count += 1

            if i % 10 == 0 or i == len(selected):
                wall = time.monotonic() - t0
                log(
                    f"Progress: {i}/{len(selected)} "
                    f"({success_count} ok, {fail_count} fail) "
                    f"wall={wall:.0f}s"
                )

    wall_elapsed = time.monotonic() - t0
    log("=" * 60)
    log(
        f"COMPLETE: {success_count} success, {fail_count} failed, "
        f"wall={wall_elapsed:.0f}s, total_llm={total_extract_time:.0f}s"
    )

    # Trigger re-embed for new blocks (they get embedded on create via API,
    # but log a reminder for any that might need it)
    log("Note: New blocks were embedded on creation via Core API.")
    log("Run memvault_re_embed.py --missing-only if any embeddings are missing.")


if __name__ == "__main__":
    main()
