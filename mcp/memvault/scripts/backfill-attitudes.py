#!/usr/bin/env python3
"""backfill-attitudes.py — Retroactive attitude extraction from preference/decision blocks.

One-time script to extract attitudes from existing memory blocks that contain
preference expressions. Uses Gemini CLI to analyze blocks in batches and
POSTs extracted attitudes to Core API /kg/attitudes/evolve.

Usage:
    python3 backfill-attitudes.py --dry-run --max-blocks 10    # preview
    python3 backfill-attitudes.py                               # full run
    python3 backfill-attitudes.py --block-types preference,decision,technical

Dependencies: gemini CLI, stdlib only (no pip packages)
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
BATCH_SIZE = 5  # blocks per Gemini call
RATE_LIMIT_SECONDS = 1

VALID_CATEGORIES = {
    "tool_behavior", "config", "architecture", "workflow",
    "preference", "technical", "naming", "syntax", "performance",
}

EXTRACTION_PROMPT = """你是態度提取專家。從以下記憶 blocks 中提取使用者的偏好、信念和原則。

每個態度用 category|fact 格式輸出，一行一條。

category 只限: tool_behavior, config, architecture, workflow, preference, technical, naming, syntax, performance

規則：
- 只提取有明確證據的態度
- 不猜測、不推斷
- 沒有態度就輸出 NONE
- 不要加其他解釋文字

範例輸出：
preference|偏好使用 Zustand 而非 Redux 管理前端狀態
architecture|模組間通訊一律走 EventBus，禁止直接 import models
tool_behavior|Claude Code 回應一律使用繁體中文

以下是待分析的記憶 blocks：
"""


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def http_get(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post(url: str, body: dict, params: dict | None = None) -> tuple[int, dict]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:300]
        try:
            return e.code, json.loads(body_txt)
        except json.JSONDecodeError:
            return e.code, {"detail": body_txt}


# ── Fetch blocks ──────────────────────────────────────────────────────────────
def fetch_blocks(block_types: list[str], max_blocks: int) -> list[dict]:
    """Fetch preference/decision blocks from Core API."""
    all_blocks = []
    for bt in block_types:
        page = 1
        while len(all_blocks) < max_blocks:
            url = f"{CORE_API}/api/memvault/blocks"
            params = {
                "space_id": SPACE_ID,
                "block_type": bt,
                "page": page,
                "page_size": min(100, max_blocks - len(all_blocks)),
            }
            data = http_get(url, params)
            items = data.get("items", [])
            if not items:
                break
            all_blocks.extend(items)
            if len(items) < params["page_size"]:
                break
            page += 1

    return all_blocks[:max_blocks]


# ── Gemini extraction ─────────────────────────────────────────────────────────
def extract_attitudes_batch(blocks: list[dict]) -> list[dict]:
    """Call Gemini to extract attitudes from a batch of blocks."""
    blocks_text = []
    for i, b in enumerate(blocks):
        topic = b.get("topic", "")
        content = b.get("content", "")
        block_type = b.get("block_type", "")
        session_id = b.get("session_id", "")
        blocks_text.append(
            f"--- Block {i+1} [{block_type}] (session: {session_id}) ---\n"
            f"Topic: {topic}\n{content}\n"
        )

    prompt_content = EXTRACTION_PROMPT + "\n".join(blocks_text)

    try:
        result = subprocess.run(
            ["gemini", "-m", GEMINI_MODEL, "-p",
             "Extract user attitudes from the blocks. Output ONLY category|fact lines or NONE."],
            input=prompt_content, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  [warn] Gemini failed (exit {result.returncode})", file=sys.stderr)
            return []

        raw = result.stdout.strip()
        if not raw or raw.upper() == "NONE":
            return []

        attitudes = []
        for line in raw.splitlines():
            line = line.strip().lstrip("- ")
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            category = parts[0].strip()
            fact = parts[1].strip() if len(parts) > 1 else ""
            if category in VALID_CATEGORIES and fact:
                attitudes.append({"category": category, "fact": fact})

        return attitudes
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  [warn] Gemini error: {e}", file=sys.stderr)
        return []


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retroactive attitude extraction from memory blocks"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-blocks", type=int, default=500)
    parser.add_argument(
        "--block-types", default="preference,decision",
        help="Comma-separated block types to scan (default: preference,decision)",
    )
    args = parser.parse_args()

    block_types = [bt.strip() for bt in args.block_types.split(",")]

    print("Memvault — backfill-attitudes.py")
    print(f"Core API    : {CORE_API}")
    print(f"Space ID    : {SPACE_ID}")
    print(f"Gemini Model: {GEMINI_MODEL}")
    print(f"Block types : {block_types}")
    print(f"Max blocks  : {args.max_blocks}")
    print(f"Mode        : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    # Fetch blocks
    print("[Phase 1] Fetching blocks from Core API ...")
    blocks = fetch_blocks(block_types, args.max_blocks)
    print(f"[Phase 1] Loaded {len(blocks)} blocks")

    if not blocks:
        print("[skip] No blocks found.")
        return

    # Process in batches
    total_attitudes = 0
    total_posted = 0
    total_failed = 0

    for i in range(0, len(blocks), BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(blocks) + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"\n[Phase 2] Batch {batch_num}/{total_batches} ({len(batch)} blocks)...", flush=True)

        attitudes = extract_attitudes_batch(batch)
        total_attitudes += len(attitudes)

        if not attitudes:
            print("  No attitudes extracted")
            continue

        print(f"  Extracted {len(attitudes)} attitude(s):")
        for att in attitudes:
            print(f"    [{att['category']}] {att['fact'][:80]}")

            if args.dry_run:
                total_posted += 1
                continue

            status, resp = http_post(
                f"{CORE_API}/api/memvault/kg/attitudes/evolve",
                {
                    "fact": att["fact"],
                    "category": att["category"],
                    "source_session": "backfill",
                },
                params={"space_id": SPACE_ID},
            )
            if status in (200, 201):
                total_posted += 1
                op = resp.get("operation", "?")
                print(f"      → {op}")
            else:
                total_failed += 1
                detail = resp.get("detail", str(resp))[:80]
                print(f"      → FAIL HTTP {status}: {detail}")

        # Rate limit between batches
        if i + BATCH_SIZE < len(blocks):
            time.sleep(RATE_LIMIT_SECONDS)

    # Report
    print(f"\n{'='*60}")
    print("  Memvault — Backfill Attitudes Report")
    print(f"{'='*60}")
    print(f"  Blocks scanned     : {len(blocks)}")
    print(f"  Attitudes extracted: {total_attitudes}")
    print(f"  Posted / dry-run   : {total_posted}")
    print(f"  Failed             : {total_failed}")
    print(f"{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
