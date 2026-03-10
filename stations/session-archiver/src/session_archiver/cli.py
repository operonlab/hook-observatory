"""CLI subcommand implementations for session-archiver."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

import structlog

from session_archiver.config import load_config

logger = structlog.get_logger(__name__)


def cmd_scan(args: list[str]) -> None:
    """Scan all sessions and update DB index."""
    parser = argparse.ArgumentParser(description="Scan sessions")
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver import db
    from session_archiver.scanner import scan_sessions
    from session_archiver.scorer import score_all

    # Ensure DB schema exists (graceful if PG down)
    db.ensure_schema(config)

    sessions = scan_sessions(config)
    scored = score_all(sessions)

    # Upsert each session into DB
    upserted = 0
    for meta, score in scored:
        if db.upsert_session(config, meta, score):
            upserted += 1

    result = {
        "scanned": len(sessions),
        "upserted": upserted,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if opts.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Scanned {len(sessions)} sessions, upserted {upserted} to DB")


def cmd_score(args: list[str]) -> None:
    """Display session scores."""
    parser = argparse.ArgumentParser(description="Score sessions")
    parser.add_argument("--top", type=int, default=0, help="Show top N only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver.scanner import scan_sessions
    from session_archiver.scorer import score_all

    sessions = scan_sessions(config)
    scored = score_all(sessions)

    if opts.top > 0:
        scored = scored[: opts.top]

    if opts.json:
        rows = [
            {
                "session_id": m.session_id[:12],
                "size_mb": round(m.file_size_bytes / 1024 / 1024, 1),
                "score": round(s.total, 1),
                "size": round(s.size, 1),
                "age": round(s.age, 1),
                "activity": round(s.activity, 1),
                "compress": round(s.compressibility, 1),
                "companion": m.has_companion,
            }
            for m, s in scored
        ]
        print(json.dumps(rows, indent=2))
    else:
        # Table format
        header = (
            f"{'Session ID':>14} {'Size MB':>8} {'Score':>6}"
            f" {'S':>5} {'A':>5} {'Act':>5} {'C':>5} {'R'}"
        )
        print(header)
        print("-" * len(header))
        for meta, score in scored:
            resumed = "Y" if meta.has_companion else "N"
            print(
                f"{meta.session_id[:12]:>14} "
                f"{meta.file_size_bytes / 1024 / 1024:>7.1f} "
                f"{score.total:>6.1f} "
                f"{score.size:>5.1f} "
                f"{score.age:>5.1f} "
                f"{score.activity:>5.1f} "
                f"{score.compressibility:>5.1f} "
                f"{resumed}"
            )
        print(f"\nTotal: {len(scored)} sessions")


def cmd_archive(args: list[str]) -> None:
    """Archive sessions based on score threshold."""
    parser = argparse.ArgumentParser(description="Archive sessions")
    parser.add_argument(
        "--execute", action="store_true", help="Actually archive (default is dry-run)"
    )
    parser.add_argument(
        "--threshold", type=int, default=None, help="Score threshold (default from config)"
    )
    parser.add_argument(
        "--summarize", action="store_true", help="Generate LLM summaries before archiving"
    )
    parser.add_argument("--embed", action="store_true", help="Generate embeddings for summaries")
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()
    threshold = opts.threshold or config.score_threshold
    dry_run = not opts.execute

    from session_archiver import db
    from session_archiver.archiver import archive_batch
    from session_archiver.scanner import scan_sessions
    from session_archiver.scorer import score_all

    if not dry_run:
        db.ensure_schema(config)

    sessions = scan_sessions(config)
    scored = score_all(sessions)

    # Filter candidates: score > threshold, age > min days, tier == hot
    min_age = config.archive_min_age_days
    now = datetime.now(UTC)
    candidates = []
    for meta, score in scored:
        age_days = (now - meta.last_modified).total_seconds() / 86400
        if score.total >= threshold and age_days >= min_age:
            candidates.append((meta, score))

    if not candidates:
        msg = f"No sessions meet threshold ({threshold}) and age ({min_age}d) criteria"
        if opts.json:
            print(json.dumps({"candidates": 0, "message": msg}))
        else:
            print(msg)
        return

    # Generate summaries if requested
    summaries: dict[str, str | None] = {}
    if opts.summarize and not dry_run:
        from session_archiver.summarizer import generate_summary

        for meta, _ in candidates:
            if meta.jsonl_path.exists():
                summaries[meta.session_id] = generate_summary(meta.jsonl_path)

    # Archive
    results = archive_batch(config, candidates, summaries=summaries, dry_run=dry_run)

    # Generate embeddings if requested
    if opts.embed and not dry_run and summaries:
        from session_archiver.embedding import get_embedding

        for sid, summary in summaries.items():
            if summary:
                emb = get_embedding(summary, config.omlx_venv, config.embedding_dim)
                if emb:
                    db.upsert_embedding(config, sid, emb)
                    db.update_summary(config, sid, summary)

    # Output
    total_saved = sum(r.get("saved_bytes", 0) for r in results)
    output = {
        "mode": "dry-run" if dry_run else "execute",
        "threshold": threshold,
        "candidates": len(candidates),
        "archived": len(results),
        "total_saved_mb": round(total_saved / 1024 / 1024, 1),
    }

    if opts.json:
        output["details"] = results
        print(json.dumps(output, indent=2))
    else:
        mode_label = "[DRY RUN] " if dry_run else ""
        print(f"{mode_label}Candidates: {len(candidates)}, Archived: {len(results)}")
        if not dry_run:
            print(f"Total saved: {total_saved / 1024 / 1024:.1f} MB")
        for r in results:
            sid = r["session_id"][:12]
            size = r["original_size"] / 1024 / 1024
            print(f"  {sid}  {size:.1f} MB", end="")
            if "compression_ratio" in r:
                print(f"  → {r['compression_ratio']:.1%} compression", end="")
            print()

        if dry_run:
            print("\nTo execute: session-archiver archive --execute")


def cmd_thaw(args: list[str]) -> None:
    """Thaw (restore) an archived session."""
    parser = argparse.ArgumentParser(description="Thaw session")
    parser.add_argument("session_id", help="Full or partial session ID (min 8 chars)")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver.thaw import thaw_session

    result = thaw_session(config, opts.session_id)
    if result:
        print(f"Session {result['session_id'][:12]} restored.")
        print(f"  Location: {result['restored_to']}")
        print(f"  Resume:   {result['resume_command']}")
    else:
        print(f"Failed to thaw session: {opts.session_id}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args: list[str]) -> None:
    """Show archive statistics."""
    parser = argparse.ArgumentParser(description="Archive status")
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver import db

    stats = db.get_stats(config)

    if stats is None:
        # DB unavailable — scan local files
        from session_archiver.scanner import scan_sessions

        sessions = scan_sessions(config)
        from pathlib import Path

        archive_dir = Path(config.archive_dir).expanduser()
        cold_files = list(archive_dir.glob("*.jsonl.zst")) if archive_dir.exists() else []

        result = {
            "hot_count": len(sessions),
            "hot_size_mb": round(sum(s.file_size_bytes for s in sessions) / 1024 / 1024, 1),
            "cold_count": len(cold_files),
            "cold_size_mb": round(sum(f.stat().st_size for f in cold_files) / 1024 / 1024, 1),
            "db_status": "offline",
        }
    else:
        result = {
            "hot_count": stats.hot_count,
            "hot_size_mb": round(stats.hot_size / 1024 / 1024, 1),
            "cold_count": stats.cold_count,
            "cold_original_mb": round(stats.cold_original_size / 1024 / 1024, 1),
            "cold_compressed_mb": round(stats.cold_compressed_size / 1024 / 1024, 1),
            "frozen_count": stats.frozen_count,
            "total_saved_mb": round(stats.total_saved / 1024 / 1024, 1),
            "compression_ratio": f"{stats.compression_ratio:.1%}"
            if stats.compression_ratio
            else "N/A",
            "db_status": "online",
        }

    if opts.json:
        print(json.dumps(result, indent=2))
    else:
        print("Session Archive Status")
        print("=" * 40)
        print(
            f"  Hot:    {result.get('hot_count', 0)} sessions ({result.get('hot_size_mb', 0)} MB)"
        )
        if "cold_original_mb" in result:
            print(
                f"  Cold:   {result.get('cold_count', 0)} sessions "
                f"({result.get('cold_original_mb', 0)} MB "
                f"→ {result.get('cold_compressed_mb', 0)} MB)"
            )
        else:
            print(
                f"  Cold:   {result.get('cold_count', 0)} archives "
                f"({result.get('cold_size_mb', 0)} MB)"
            )
        print(f"  Frozen: {result.get('frozen_count', 0)} sessions")
        if "total_saved_mb" in result:
            print(
                f"  Saved:  {result.get('total_saved_mb', 0)} MB "
                f"({result.get('compression_ratio', 'N/A')})"
            )
        print(f"  DB:     {result.get('db_status', 'unknown')}")


def cmd_search(args: list[str]) -> None:
    """Search archived sessions by summary."""
    parser = argparse.ArgumentParser(description="Search sessions")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver import db
    from session_archiver.embedding import get_embedding

    # Try semantic search first
    results = []
    query_emb = get_embedding(opts.query, config.omlx_venv, config.embedding_dim)
    if query_emb:
        results = db.search_by_embedding(config, query_emb, limit=opts.limit)

    # Fallback to ILIKE if no results or embedding failed
    if not results:
        results = db.search_by_text(config, opts.query, limit=opts.limit)

    if opts.json:
        rows = [
            {
                "session_id": r.session_id[:12],
                "summary": r.summary,
                "tier": r.tier,
                "score": r.score,
                "archived_at": r.archived_at,
            }
            for r in results
        ]
        print(json.dumps(rows, indent=2))
    else:
        if not results:
            print(f"No results for: {opts.query}")
            return
        print(f"Results for '{opts.query}':")
        for r in results:
            tier_icon = {"hot": "H", "cold": "C", "frozen": "F"}.get(r.tier, "?")
            summary = (r.summary or "")[:60]
            print(f"  [{tier_icon}] {r.session_id[:12]}  {summary}")
        print(f"\n{len(results)} result(s)")
