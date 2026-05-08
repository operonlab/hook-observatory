#!/usr/bin/env python3
"""Batch triple re-extraction — run extract_triples.py v2 on all session transcripts.

2026-05-08 中文化重構：因 truncate triples 表後，需要重抽所有 P0+P1 session
的 triples，使用新的中文 prompt + envelope 9 欄抽取。

Usage:
    cd /Users/joneshong/workshop
    PYTHONPATH=core/src ~/.local/bin/python3 \\
        mcp/memvault/scripts/re_extract_triples_batch.py [options]

Options:
    --priority P0|P1|P2|ALL  Priority tier (default: ALL = P0+P1, skip P2)
    --parallel N             Parallel workers (default: 4)
    --dry-run                List only, no extraction
    --limit N                Max sessions
    --resume                 Skip sessions already in progress JSONL
    --no-rate-limit          Disable rate limit (default: no rate limit per plan)

Priority tiers:
    P0: Sessions never extracted (no blocks in DB) — should not exist after Phase 1
    P1: Sessions with existing blocks (re-extract triples for them)
    P2: Small sessions (< 10KB) — skipped
    ALL: P0 + P1 (skip P2)

Progress JSONL:
    ~/Claude/memvault/logs/re-extract-triples-progress.jsonl
    每 session 完成寫一行 {session_id, success, elapsed_s, triples_count, ts}
    用 --resume 重跑時自動 skip 已完成。

Differences from re_extract_batch.py:
    - 跑 extract_triples.py（產 triples）而非 extract.py（產 blocks）
    - 不需要 soft-delete（triples 已 TRUNCATE）
    - extract_triples.py 失敗不會 invalidate blocks
"""

from __future__ import annotations

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
TRANSCRIPT_DIR = Path.home() / ".claude" / "projects" / "-Users-joneshong-workshop"
EXTRACT_TRIPLES_SCRIPT = Path(__file__).parent / "extract_triples.py"
PYTHON = str(Path.home() / ".local" / "bin" / "python3")
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "re-extract-triples-batch.log"
PROGRESS_FILE = LOG_DIR / "re-extract-triples-progress.jsonl"
DB_URL = "postgresql+psycopg://joneshong:dev_12345@localhost:5432/workshop"
MIN_TRANSCRIPT_SIZE = 10_000  # 10KB

LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[triples-batch] {ts} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_sessions_with_blocks() -> set[str]:
    """Get session IDs that have blocks in DB (eligible for triple re-extraction)."""
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


def load_progress() -> set[str]:
    """讀 progress JSONL，回傳已成功抽過 triples 的 session_id 集合."""
    if not PROGRESS_FILE.exists():
        return set()
    completed = set()
    with open(PROGRESS_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("success"):
                    completed.add(rec["session_id"])
            except json.JSONDecodeError:
                continue
    return completed


def write_progress(session_id: str, success: bool, elapsed_s: float, triples_count: int = 0) -> None:
    """單筆寫 progress JSONL."""
    record = {
        "session_id": session_id,
        "success": success,
        "elapsed_s": round(elapsed_s, 2),
        "triples_count": triples_count,
        "ts": datetime.now().isoformat(),
    }
    with open(PROGRESS_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def classify_transcripts(
    exclude_sessions: set[str] | None = None,
) -> dict[str, list[tuple[Path, int]]]:
    """Classify transcripts into priority tiers.

    對 triples 重抽而言：
    - 有 blocks 的 session（無論 size）→ P1（需要重抽）
    - 沒 blocks 但 size ≥ 10KB → P0（先跑 extract.py 產 blocks 再說，Phase 1+2 已含）
    - 沒 blocks 且 size < 10KB → P2（雜訊，skip）
    """
    has_blocks = get_sessions_with_blocks()
    exclude = exclude_sessions or set()
    tiers = {"P0": [], "P1": [], "P2": []}

    for t in TRANSCRIPT_DIR.glob("*.jsonl"):
        sid = t.stem
        if sid in exclude:
            continue
        size = t.stat().st_size

        if sid in has_blocks:
            # Triples 重抽主要對象：有 blocks 的 session
            tiers["P1"].append((t, size))
        else:
            if size >= MIN_TRANSCRIPT_SIZE:
                tiers["P0"].append((t, size))
            else:
                tiers["P2"].append((t, size))

    for tier in tiers.values():
        tier.sort(key=lambda x: x[1], reverse=True)
    return tiers


def run_triple_extraction(transcript: Path, env: dict) -> tuple[str, bool, float]:
    """Run extract_triples.py on a single transcript. Returns (session_id, success, elapsed)."""
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
            [PYTHON, str(EXTRACT_TRIPLES_SCRIPT)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,  # 10 min per session
        )
        elapsed = time.monotonic() - t0
        success = result.returncode == 0
        if not success:
            log(f"  FAIL {sid}: exit {result.returncode}; stderr={result.stderr[-300:]}")
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
    parser = argparse.ArgumentParser(description="Batch triple re-extraction for memvault")
    parser.add_argument(
        "--priority", choices=["P0", "P1", "P2", "ALL"], default="ALL",
        help="Priority tier (default: ALL = P0+P1, skip P2)",
    )
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip sessions already successful in progress JSONL"
    )
    parser.add_argument(
        "--no-rate-limit", action="store_true", default=True,
        help="Disable rate limit (default per plan: no rate limit, parallel naturally throttles)",
    )
    args = parser.parse_args()

    log("=" * 60)
    log("Memvault batch triple re-extraction (2026-05-08 中文化重構)")
    log("=" * 60)

    # Auto-exclude active sessions (mtime < 5 min)
    exclude = set(args.exclude)
    now = time.time()
    for t in TRANSCRIPT_DIR.glob("*.jsonl"):
        if now - t.stat().st_mtime < 300:
            exclude.add(t.stem)
            log(f"Auto-excluding active session: {t.stem}")

    # Resume：skip 已成功跑過的 session
    if args.resume:
        completed = load_progress()
        if completed:
            log(f"Resume mode: skipping {len(completed)} already-completed sessions")
            exclude |= completed

    tiers = classify_transcripts(exclude_sessions=exclude)
    for tier_name, sessions in tiers.items():
        total_mb = sum(s for _, s in sessions) / 1024 / 1024
        log(f"{tier_name}: {len(sessions)} sessions ({total_mb:.1f} MB)")

    if args.priority == "ALL":
        selected = tiers["P0"] + tiers["P1"]
    else:
        selected = tiers[args.priority]

    if args.limit > 0:
        selected = selected[: args.limit]

    if not selected:
        log("No sessions to process.")
        return

    log(f"Selected: {len(selected)} sessions for triple extraction")

    if args.dry_run:
        for t, size in selected[:20]:
            log(f"  {t.stem} ({size // 1024}KB)")
        if len(selected) > 20:
            log(f"  ... and {len(selected) - 20} more")
        return

    # Build env
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["MEMVAULT_SKIP_RECALL"] = "1"
    # 預設 LLM：plan 寫的 DeepSeek-V3 / Gemini-2.5-Pro
    # extract_triples.py 透過 MEMVAULT_LLM 環境變數選擇
    env.setdefault("MEMVAULT_LLM", os.environ.get("MEMVAULT_LLM", "gemini"))

    log(f"LLM: {env.get('MEMVAULT_LLM')}")
    log(f"Workers: {args.parallel} (no rate limit)")

    t0 = time.monotonic()
    success_count = 0
    fail_count = 0
    total_extract_time = 0.0

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(run_triple_extraction, transcript, env): (transcript, size)
            for transcript, size in selected
        }

        for i, future in enumerate(as_completed(futures), 1):
            transcript, _size = futures[future]
            sid, success, elapsed = future.result()
            total_extract_time += elapsed

            # 即時寫 progress JSONL（中斷續跑的關鍵）
            write_progress(sid, success, elapsed)

            if success:
                success_count += 1
            else:
                fail_count += 1

            if i % 10 == 0 or i == len(selected):
                wall = time.monotonic() - t0
                log(
                    f"Progress: {i}/{len(selected)} "
                    f"({success_count} ok, {fail_count} fail) "
                    f"wall={wall:.0f}s avg={total_extract_time/i:.1f}s/session"
                )

    wall_elapsed = time.monotonic() - t0
    log("=" * 60)
    log(
        f"COMPLETE: {success_count} success, {fail_count} failed, "
        f"wall={wall_elapsed:.0f}s, total_llm={total_extract_time:.0f}s"
    )
    log(f"Progress log: {PROGRESS_FILE}")
    log("Next step: trigger ws-memvault-synthesis to rebuild communities + summaries")


if __name__ == "__main__":
    main()
