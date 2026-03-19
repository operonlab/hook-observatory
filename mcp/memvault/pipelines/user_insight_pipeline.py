#!/usr/bin/env python3
"""user_insight_pipeline.py — Generate natural language insights from interest profiles.

Fetches the latest interest snapshot and knowledge gaps from Core API,
uses Haiku LLM to generate 2-3 insight sentences, and stores them as
AttitudeFacts with category="meta_insight".

Usage:
    python3 mcp/memvault/pipelines/user_insight_pipeline.py
    python3 mcp/memvault/pipelines/user_insight_pipeline.py --space-id default --dry-run

Environment:
    CORE_API_URL      — defaults to http://localhost:8801
    MEMVAULT_SPACE_ID — defaults to default
"""

import argparse
import json
import logging
import os
import sys

# Add core to path for imports
WORKSHOP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(WORKSHOP_ROOT, "core"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8801")


async def fetch_attention_profile(space_id: str) -> dict:
    """Fetch attention profile from Core API."""
    import httpx

    url = f"{CORE_API_URL}/api/memvault/interest/attention"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params={"space_id": space_id})
        resp.raise_for_status()
        return resp.json()


async def fetch_knowledge_gaps(space_id: str, days: int = 7) -> list[dict]:
    """Fetch knowledge gaps from Core API."""
    import httpx

    url = f"{CORE_API_URL}/api/memvault/interest/gaps"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params={"space_id": space_id, "days": days})
        resp.raise_for_status()
        return resp.json()


async def generate_insight_text(
    attention: dict, gaps: list[dict], dry_run: bool = False
) -> str | None:
    """Use Haiku to generate natural language insight from attention + gaps data."""
    if not attention and not gaps:
        logger.info("No attention data or gaps — skipping insight generation")
        return None

    # Build prompt
    active_entities = [e for e, level in attention.items() if level == "active"]
    fading_entities = [e for e, level in attention.items() if level == "fading"]
    historical_entities = [e for e, level in attention.items() if level == "historical"]

    gap_lines = []
    for g in gaps[:5]:
        gap_lines.append(f"- 「{g['query']}」 failed {g['fail_count']} times")

    prompt = f"""Based on the user's recent memvault query patterns, \
generate 2-3 concise insight sentences in 繁體中文.

Active focus areas (queried in last 7 days): {', '.join(active_entities[:10]) or 'none'}
Fading topics (queried 30-90 days ago): {', '.join(fading_entities[:10]) or 'none'}
Historical topics (7-30 days): {', '.join(historical_entities[:10]) or 'none'}

Knowledge gaps (queries with poor results):
{chr(10).join(gap_lines) or 'None detected'}

Guidelines:
- Be specific about which topics are active vs fading
- If there are knowledge gaps, suggest enriching those areas
- Keep it under 100 words total
- Use 繁體中文
- Do NOT include pleasantries or meta-commentary"""

    if dry_run:
        logger.info("DRY RUN — would send to Haiku:\n%s", prompt)
        return f"[DRY RUN] Active: {', '.join(active_entities[:5])}; Gaps: {len(gaps)}"

    # Use Haiku via the shared LLM helper
    try:
        from src.shared.llm_haiku import haiku_extract

        result = await haiku_extract(prompt)
        if result:
            return result.strip()
    except Exception as e:
        logger.warning("Haiku extraction failed: %s", e)

    return None


async def store_insight(space_id: str, insight_text: str, dry_run: bool = False) -> dict | None:
    """Store insight as an AttitudeFact with category=meta_insight."""
    if dry_run:
        logger.info("DRY RUN — would store: %s", insight_text[:100])
        return {"dry_run": True}

    import httpx

    url = f"{CORE_API_URL}/api/memvault/kg/attitudes"
    payload = {
        "fact": insight_text,
        "category": "meta_insight",
        "source_sessions": [],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, params={"space_id": space_id})
        resp.raise_for_status()
        return resp.json()


async def run_pipeline(space_id: str, dry_run: bool = False) -> dict:
    """Run the full insight pipeline."""
    logger.info("=== User Insight Pipeline ===")
    logger.info("Space: %s | Dry run: %s", space_id, dry_run)

    # Step 1: Fetch data
    attention = await fetch_attention_profile(space_id)
    gaps = await fetch_knowledge_gaps(space_id)

    logger.info(
        "Fetched: %d attention entities, %d knowledge gaps",
        len(attention), len(gaps),
    )

    if not attention and not gaps:
        logger.info("No data available — skipping insight generation")
        return {"status": "skipped", "reason": "no_data"}

    # Step 2: Generate insight
    insight_text = await generate_insight_text(attention, gaps, dry_run=dry_run)
    if not insight_text:
        return {"status": "skipped", "reason": "generation_failed"}

    logger.info("Generated insight: %s", insight_text[:120])

    # Step 3: Store as AttitudeFact
    result = await store_insight(space_id, insight_text, dry_run=dry_run)

    return {
        "status": "ok",
        "insight": insight_text,
        "stored": result,
        "attention_entities": len(attention),
        "knowledge_gaps": len(gaps),
    }


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description="Generate user insights from query history")
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(run_pipeline(args.space_id, dry_run=args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") != "ok":
        sys.exit(0)  # Not an error — just no data


if __name__ == "__main__":
    main()
