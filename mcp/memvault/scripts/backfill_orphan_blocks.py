#!/usr/bin/env python3
"""Backfill orphan blocks from JSONL fallback files into memvault Core API.

These blocks were extracted successfully but failed to POST due to HTTP 401
(missing X-Internal-Key header in extract.py, fixed 2026-04-08).

Usage:
    python3 backfill_orphan_blocks.py                    # dry-run (default)
    python3 backfill_orphan_blocks.py --execute          # actually POST
    python3 backfill_orphan_blocks.py --execute --month 2026-04  # specific month
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# ── Config ──
EXTRACTIONS_DIR = Path.home() / "Claude" / "memvault" / "extractions"
CORE_API_BASE = os.environ.get("MEMVAULT_API_URL", "http://localhost:10000")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
BATCH_DELAY = 0.1  # seconds between POSTs to avoid overwhelming the API


def load_env() -> str:
    """Load CORE_INTERNAL_API_KEY from core/.env if not in environment."""
    key = os.environ.get("CORE_INTERNAL_API_KEY", "")
    if not key:
        env_file = Path(__file__).resolve().parents[3] / "core" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CORE_INTERNAL_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key


def post_block(block: dict, api_key: str) -> tuple[int, str]:
    """POST a block to Core API. Returns (status_code, response_body)."""
    url = f"{CORE_API_BASE}/api/memvault/blocks?space_id={SPACE_ID}"
    payload = {
        "content": block["content"],
        "block_type": block.get("block_type", "knowledge"),
        "tags": block.get("tags", []),
        "source_session": block.get("session_id"),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Key": api_key,
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 0, str(e)


def collect_jsonl_files(month: str | None = None) -> list[Path]:
    """Collect all JSONL files, optionally filtered by month (YYYY-MM)."""
    files = []
    for month_dir in sorted(EXTRACTIONS_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        if month and month_dir.name != month:
            continue
        for f in sorted(month_dir.glob("*.jsonl")):
            files.append(f)
    return files


def main() -> None:
    execute = "--execute" in sys.argv
    month = None
    for i, arg in enumerate(sys.argv):
        if arg == "--month" and i + 1 < len(sys.argv):
            month = sys.argv[i + 1]

    api_key = load_env()
    if not api_key:
        print("ERROR: CORE_INTERNAL_API_KEY not found in env or core/.env")
        sys.exit(1)

    files = collect_jsonl_files(month)
    if not files:
        print(f"No JSONL files found in {EXTRACTIONS_DIR}" + (f" (month={month})" if month else ""))
        return

    total_blocks = 0
    total_success = 0
    total_skip = 0
    total_fail = 0

    for f in files:
        blocks = []
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                blocks.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        print(f"\n{'[DRY-RUN] ' if not execute else ''}{f.name}: {len(blocks)} blocks")

        for i, block in enumerate(blocks):
            total_blocks += 1
            content = block.get("content", "")
            topic = block.get("topic", "?")[:50]

            if not content or len(content) < 20:
                total_skip += 1
                continue

            if execute:
                status, body = post_block(block, api_key)
                if 200 <= status < 300:
                    total_success += 1
                    block_id = json.loads(body).get("id", "?")[:12] if body.startswith("{") else "?"
                    print(f"  [{i + 1}/{len(blocks)}] ✓ {status} id={block_id} | {topic}")
                else:
                    total_fail += 1
                    print(f"  [{i + 1}/{len(blocks)}] ✗ {status} | {topic} | {body[:100]}")
                time.sleep(BATCH_DELAY)
            else:
                print(f"  [{i + 1}/{len(blocks)}] {block.get('block_type', '?'):10} | {topic}")
                total_success += 1  # count as would-succeed for dry-run

    print(f"\n{'=' * 50}")
    print(f"{'[DRY-RUN] ' if not execute else ''}Summary:")
    print(f"  Total blocks:  {total_blocks}")
    print(f"  {'Would post' if not execute else 'Posted OK'}:  {total_success}")
    print(f"  Skipped:       {total_skip}")
    if execute:
        print(f"  Failed:        {total_fail}")
    if not execute:
        print("\nRun with --execute to actually POST blocks to Core API.")


if __name__ == "__main__":
    main()
