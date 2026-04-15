#!/usr/bin/env python3
"""Replay queued triples from local JSONL fallback into Core API.

Walks ~/Claude/memvault/triples/**/*.jsonl and POSTs each record to
/api/memvault/kg/triples/batch with the proper X-Internal-Key header.

Used to backfill triples that were stranded by the 9-day 401 window
(extract_triples.py missing auth header). Idempotency depends on Core-side
dedup — re-running may or may not create duplicates depending on the KG
service's behavior.

Usage:
  python3 replay_triples_jsonl.py              # replay all
  python3 replay_triples_jsonl.py --dry-run    # show what would be sent
  python3 replay_triples_jsonl.py 2026-04-14   # replay one date
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TRIPLES_BASE = Path.home() / "Claude" / "memvault" / "triples"
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:10000")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
KG_BATCH_URL = f"{CORE_API}/api/memvault/kg/triples/batch"
INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")


def post_batch(body: dict, dry_run: bool) -> tuple[int, str]:
    if dry_run:
        return 0, "dry-run"
    if not INTERNAL_KEY:
        return 0, "CORE_INTERNAL_API_KEY not set in env"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{KG_BATCH_URL}?space_id={SPACE_ID}",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Key": INTERNAL_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:200]
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return e.code, body_text
    except Exception as e:
        return 0, f"error: {e}"


def build_body(rec: dict) -> dict | None:
    session_id = rec.get("session_id") or ""
    triples = rec.get("triples") or []
    topic = rec.get("topic") or ""
    tags = rec.get("tags") or []
    timestamp = rec.get("timestamp") or ""
    if not session_id or not triples:
        return None
    batch_triples = [
        {
            "s": t.get("s", ""),
            "p": t.get("p", ""),
            "o": t.get("o", ""),
            "session_id": session_id,
            "topic": topic,
            "tags": tags,
        }
        for t in triples
        if t.get("s") and t.get("p") and t.get("o")
    ]
    if not batch_triples:
        return None
    body: dict = {
        "triples": batch_triples,
        "session_id": session_id,
        "topic": topic,
        "tags": tags,
    }
    if timestamp:
        body["timestamp"] = timestamp
    return body


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    date_filter = next((a for a in args if a.startswith("2026-") or a.startswith("2025-")), None)

    if not TRIPLES_BASE.exists():
        print(f"No triples directory: {TRIPLES_BASE}")
        return 0

    files = sorted(TRIPLES_BASE.rglob("*.jsonl"))
    if date_filter:
        files = [f for f in files if date_filter in f.name]

    if not files:
        print("No JSONL files found.")
        return 0

    total_records = 0
    total_triples = 0
    sent = 0
    failed = 0
    skipped = 0
    errors: list[str] = []

    for fp in files:
        print(f"\n=== {fp.name} ===")
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            print(f"  read error: {e}")
            continue
        for idx, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            total_records += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                errors.append(f"{fp.name}#{idx}: invalid JSON")
                continue
            if rec.get("skip") is True:
                skipped += 1
                continue
            body = build_body(rec)
            if body is None:
                skipped += 1
                continue
            n = len(body["triples"])
            total_triples += n
            status, resp = post_batch(body, dry_run)
            if dry_run:
                print(
                    f"  [DRY] session={rec.get('session_id', '')[:12]}... triples={n} topic={rec.get('topic', '')[:40]}"
                )
                sent += 1
            elif status in (200, 201):
                print(f"  OK   session={rec.get('session_id', '')[:12]}... triples={n}")
                sent += 1
            else:
                failed += 1
                msg = f"{fp.name}#{idx}: HTTP {status} {resp[:100]}"
                errors.append(msg)
                print(f"  FAIL {msg}")

    print("\n=== Summary ===")
    print(f"Files scanned : {len(files)}")
    print(f"Records total : {total_records}")
    print(f"Triples total : {total_triples}")
    print(f"Sent OK       : {sent}")
    print(f"Failed        : {failed}")
    print(f"Skipped       : {skipped}")
    if errors and not dry_run:
        print("\nErrors (first 10):")
        for e in errors[:10]:
            print(f"  - {e}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
