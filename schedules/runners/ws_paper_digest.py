#!/Users/joneshong/.local/bin/python3
"""Daily paper digest pipeline — arXiv fetch → dedup → relevance → digest → tag.

Pipeline:
  1. Fetch recent arXiv papers (cs.IR/CL/AI/SE/MA, last 24h, up to 50 papers)
  2. Dedup by arxiv_id against paper.articles table
  3. Score relevance via oMLX embedding similarity vs WATCH_TOPICS
  4. Generate Haiku digests for top-relevance papers (score >= 0.35)
  5. Tag papers with high relevance + effort ≤ 3d as cannibalize-candidate
  6. Monday: emit weekly rollup summary

Cronicle event: ws-paper-digest
Schedule: daily 06:30
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Path bootstrap ────────────────────────────────────────────────────────────

HOME = Path.home()
WORKSHOP = HOME / "workshop"
PYTHON = HOME / ".local/bin/python3"
LOG_DIR = WORKSHOP / "outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-paper-digest.log"

# Add workshop to sys.path for shared imports
sys.path.insert(0, str(WORKSHOP))

# Extend PATH for subprocesses
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)

# ── Quota Gate ────────────────────────────────────────────────────────────────

from schedules.lib.quota_gate import request_clearance  # noqa: E402

request_clearance("ws-paper-digest")

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), mode="a"),
    ],
)
logger = logging.getLogger("ws_paper_digest")

# ── Configuration ─────────────────────────────────────────────────────────────

# Relevance threshold: papers below this score are skipped for digest generation
MIN_RELEVANCE_FOR_DIGEST = 0.35

# Cannibalize-candidate thresholds
CANNIBALIZE_RELEVANCE_THRESHOLD = 0.65  # workshop_relevance = high
CANNIBALIZE_EFFORT_DAYS_MAX = 3  # effort_estimate <= 3d

# Number of days back to fetch (normally 1, use 2 on Monday to catch weekend papers)
_MONDAY_WEEKDAY = 0  # datetime.weekday() == 0

# Database connection URL
_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/workshop",
)

# Default space_id for automated paper ingestion
_SYSTEM_SPACE_ID = os.environ.get("PAPER_SPACE_ID", "00000000-0000-0000-0000-000000000001")


# ── Helpers ───────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    """Print with timestamp prefix (also captured by file handler above)."""
    logger.info(msg)


def _parse_effort_days(effort_str: str) -> float | None:
    """Parse effort estimate string to days for threshold comparison.

    Examples: '0.5d' -> 0.5, '3d' -> 3.0, '1w' -> 7.0, '' -> None
    """
    if not effort_str:
        return None
    effort_str = effort_str.strip().lower()
    try:
        if effort_str.endswith("w"):
            return float(effort_str[:-1]) * 7
        if effort_str.endswith("d"):
            return float(effort_str[:-1])
        return float(effort_str)
    except (ValueError, IndexError):
        return None


def _should_cannibalize(paper: dict) -> bool:
    """Check if a paper + digest qualifies as a cannibalize candidate.

    Criteria:
    - digest.workshop_relevance == "high"
    - digest.effort_estimate parsed days <= CANNIBALIZE_EFFORT_DAYS_MAX
    - digest.confidence >= 0.6
    """
    digest = paper.get("digest")
    if not digest:
        return False

    if digest.get("workshop_relevance") != "high":
        return False

    if digest.get("confidence", 0.0) < 0.6:
        return False

    effort_days = _parse_effort_days(digest.get("effort_estimate", ""))
    if effort_days is None:
        return False

    return effort_days <= CANNIBALIZE_EFFORT_DAYS_MAX


# ── Weekly rollup ─────────────────────────────────────────────────────────────


def _weekly_rollup_summary(
    papers_with_digest: list[dict],
    new_count: int,
    skipped_count: int,
    cannibalize_candidates: list[dict],
) -> str:
    """Generate Monday weekly rollup text summary."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        f"=== Paper Digest Weekly Rollup ({today}) ===",
        f"Papers stored this week: {new_count} new, {skipped_count} duplicates skipped",
        f"Digests generated: {len(papers_with_digest)}",
        f"Cannibalize candidates: {len(cannibalize_candidates)}",
        "",
    ]

    if cannibalize_candidates:
        lines.append("## Top Cannibalize Candidates")
        for i, paper in enumerate(cannibalize_candidates[:5], 1):
            digest = paper.get("digest", {})
            lines.append(
                f"{i}. [{digest.get('workshop_relevance', '?').upper()}] {paper['title'][:80]}"
            )
            lines.append(f"   arxiv_id: {paper.get('arxiv_id', 'N/A')}")
            lines.append(f"   One-liner: {digest.get('one_liner', 'N/A')}")
            lines.append(
                f"   Effort: {digest.get('effort_estimate', 'N/A')} | "
                f"Modules: {', '.join(digest.get('applicable_modules', []))}"
            )
            lines.append(f"   Action: {digest.get('actionable_insight', 'N/A')[:120]}")
            lines.append("")

    if papers_with_digest and not cannibalize_candidates:
        lines.append("No high-relevance + low-effort papers found this run.")

    return "\n".join(lines)


# ── DB session factory ────────────────────────────────────────────────────────


async def _get_db_session():
    """Create an async SQLAlchemy session. Returns None if DB unavailable."""
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_async_engine(_DB_URL, pool_pre_ping=True, pool_size=2)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return factory()
    except Exception as exc:
        logger.error("ws_paper_digest: DB connection failed — %s", exc)
        return None


# ── Tag update helper ─────────────────────────────────────────────────────────


async def _tag_cannibalize_candidate(db, arxiv_id: str) -> None:
    """Add 'cannibalize-candidate' tag to an article by arxiv_id."""
    from sqlalchemy import text

    try:
        await db.execute(
            text(
                """
                UPDATE paper.articles
                SET tags = array_append(
                    CASE WHEN 'cannibalize-candidate' = ANY(tags) THEN tags
                         ELSE tags END,
                    'cannibalize-candidate'
                )
                WHERE arxiv_id = :arxiv_id
                  AND NOT ('cannibalize-candidate' = ANY(tags))
                  AND deleted_at IS NULL
                """
            ),
            {"arxiv_id": arxiv_id},
        )
        logger.info("ws_paper_digest: tagged cannibalize-candidate for %s", arxiv_id)
    except Exception as exc:
        logger.warning("ws_paper_digest: failed to tag %s — %s", arxiv_id, exc)


async def _store_digest(db, arxiv_id: str, digest: dict) -> None:
    """Upsert digest record for an article."""
    import json as _json

    from sqlalchemy import text

    try:
        await db.execute(
            text(
                """
                INSERT INTO paper.digests (
                    id, article_id,
                    one_liner, key_findings, workshop_relevance,
                    applicable_modules, actionable_insight, effort_estimate,
                    confidence, model_used, generated_at
                )
                SELECT
                    gen_random_uuid(), a.id,
                    :one_liner, :key_findings::jsonb, :workshop_relevance,
                    :applicable_modules::jsonb, :actionable_insight, :effort_estimate,
                    :confidence, :model_used, NOW()
                FROM paper.articles a
                WHERE a.arxiv_id = :arxiv_id AND a.deleted_at IS NULL
                ON CONFLICT (article_id)
                DO UPDATE SET
                    one_liner = EXCLUDED.one_liner,
                    key_findings = EXCLUDED.key_findings,
                    workshop_relevance = EXCLUDED.workshop_relevance,
                    applicable_modules = EXCLUDED.applicable_modules,
                    actionable_insight = EXCLUDED.actionable_insight,
                    effort_estimate = EXCLUDED.effort_estimate,
                    confidence = EXCLUDED.confidence,
                    model_used = EXCLUDED.model_used,
                    generated_at = EXCLUDED.generated_at
                """
            ),
            {
                "arxiv_id": arxiv_id,
                "one_liner": digest["one_liner"],
                "key_findings": _json.dumps(digest["key_findings"]),
                "workshop_relevance": digest["workshop_relevance"],
                "applicable_modules": _json.dumps(digest["applicable_modules"]),
                "actionable_insight": digest["actionable_insight"],
                "effort_estimate": digest["effort_estimate"],
                "confidence": digest["confidence"],
                "model_used": digest["model_used"],
            },
        )
    except Exception as exc:
        logger.warning("ws_paper_digest: failed to store digest for %s — %s", arxiv_id, exc)


# ── Main pipeline ─────────────────────────────────────────────────────────────


async def run_pipeline() -> None:
    """Execute the full paper digest pipeline."""
    from core.src.modules.paper.arxiv_fetcher import (
        WATCH_CATEGORIES,
        WATCH_TOPICS,
        fetch_arxiv_papers,
        score_relevance,
        store_new_papers,
    )
    from core.src.modules.paper.digest_generator import generate_digest

    today = datetime.now(UTC)
    is_monday = today.weekday() == _MONDAY_WEEKDAY

    # Fetch a larger window on Monday to catch any weekend papers
    days_back = 3 if is_monday else 1

    log(f"=== Paper Digest Pipeline started — {today.strftime('%Y-%m-%d %H:%M UTC')} ===")
    log(f"is_monday={is_monday}, days_back={days_back}")

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    log("Step 1: Fetching arXiv papers...")
    papers = await fetch_arxiv_papers(
        categories=WATCH_CATEGORIES,
        max_results=50,
        days_back=days_back,
    )
    log(f"  Fetched {len(papers)} papers")

    if not papers:
        log("No papers fetched. Pipeline complete (no-op).")
        return

    # ── Step 2: Relevance scoring ─────────────────────────────────────────────
    log("Step 2: Scoring relevance via oMLX embeddings...")
    papers = await score_relevance(papers, topics=WATCH_TOPICS)
    above_threshold = [p for p in papers if p.get("relevance_score", 0) >= MIN_RELEVANCE_FOR_DIGEST]
    log(
        f"  Scored {len(papers)} papers; {len(above_threshold)} above "
        f"threshold ({MIN_RELEVANCE_FOR_DIGEST})"
    )

    # ── Step 3: Store new papers (dedup) ──────────────────────────────────────
    log("Step 3: Storing new papers (dedup by arxiv_id)...")
    db = await _get_db_session()

    new_count = 0
    skipped_count = 0

    if db is not None:
        async with db:
            new_count, skipped_count = await store_new_papers(
                db, space_id=_SYSTEM_SPACE_ID, papers=papers
            )
        log(f"  Stored {new_count} new papers, skipped {skipped_count} duplicates")
    else:
        log("  WARNING: DB unavailable — skipping store (dry run mode)")

    # ── Step 4: Digest generation ─────────────────────────────────────────────
    log(f"Step 4: Generating digests for {len(above_threshold)} relevant papers...")

    papers_with_digest: list[dict] = []
    digest_errors = 0

    for paper in above_threshold:
        arxiv_id = paper.get("arxiv_id", "")
        score = paper.get("relevance_score", 0)
        log(f"  Generating digest: {arxiv_id} (score={score:.3f}) — {paper['title'][:60]}")

        digest = await generate_digest(
            title=paper["title"],
            abstract=paper["abstract"],
            arxiv_id=arxiv_id,
        )

        if digest is None:
            logger.warning("  WARN: digest generation failed for %s", arxiv_id)
            digest_errors += 1
            continue

        enriched = dict(paper)
        enriched["digest"] = digest
        papers_with_digest.append(enriched)

        log(
            f"    relevance={digest['workshop_relevance']} "
            f"confidence={digest['confidence']:.2f} "
            f"effort={digest['effort_estimate']} "
            f"model={digest['model_used']}"
        )

        # Store digest in DB
        if db is not None:
            db2 = await _get_db_session()
            if db2 is not None:
                async with db2:
                    await _store_digest(db2, arxiv_id, digest)
                    await db2.commit()

    log(f"  Digests generated: {len(papers_with_digest)}, errors: {digest_errors}")

    # ── Step 5: Tag cannibalize candidates ────────────────────────────────────
    log("Step 5: Tagging cannibalize candidates...")
    cannibalize_candidates: list[dict] = []

    for paper in papers_with_digest:
        if _should_cannibalize(paper):
            cannibalize_candidates.append(paper)
            arxiv_id = paper.get("arxiv_id", "")
            digest = paper["digest"]
            log(f"  CANNIBALIZE CANDIDATE: {arxiv_id} — {digest.get('one_liner', '')[:80]}")

            if db is not None:
                db3 = await _get_db_session()
                if db3 is not None:
                    async with db3:
                        await _tag_cannibalize_candidate(db3, arxiv_id)
                        await db3.commit()

    log(f"  Tagged {len(cannibalize_candidates)} cannibalize candidates")

    # ── Step 6: Monday weekly rollup ─────────────────────────────────────────
    if is_monday:
        log("Step 6: Monday weekly rollup...")
        rollup = _weekly_rollup_summary(
            papers_with_digest=papers_with_digest,
            new_count=new_count,
            skipped_count=skipped_count,
            cannibalize_candidates=cannibalize_candidates,
        )
        print(rollup)

        # Save rollup to outputs
        rollup_dir = WORKSHOP / "outputs/paper"
        rollup_dir.mkdir(parents=True, exist_ok=True)
        rollup_file = rollup_dir / f"weekly-rollup-{today.strftime('%Y-%m-%d')}.txt"
        rollup_file.write_text(rollup, encoding="utf-8")
        log(f"  Rollup saved to {rollup_file}")
    else:
        log("Step 6: Skipped (not Monday)")

    # ── Summary ───────────────────────────────────────────────────────────────
    log(
        f"=== Pipeline complete: {new_count} new papers, "
        f"{len(papers_with_digest)} digests, "
        f"{len(cannibalize_candidates)} cannibalize candidates ==="
    )


def main() -> None:
    """Entry point — runs the async pipeline."""
    log("ws_paper_digest: starting...")
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        log("ws_paper_digest: interrupted")
        sys.exit(0)
    except Exception as exc:
        logger.exception("ws_paper_digest: pipeline failed — %s", exc)
        sys.exit(1)
    log("ws_paper_digest: done.")


if __name__ == "__main__":
    _lock_path = f"/tmp/{Path(__file__).stem}.lock"  # noqa: S108
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()
