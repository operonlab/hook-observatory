"""CLI subcommand implementations for session-archiver."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from session_archiver.config import load_config

logger = structlog.get_logger(__name__)


def cmd_scan(args: list[str]) -> None:
    """Scan all sessions and update DB index. With --summarize, also promote hot→warm."""
    parser = argparse.ArgumentParser(description="Scan sessions")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--session-id", help="Scan only this session (fast path)")
    parser.add_argument(
        "--summarize", action="store_true", help="Generate summaries for warm candidates"
    )
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver import db
    from session_archiver.scanner import scan_sessions
    from session_archiver.scorer import score_all

    # Ensure DB schema exists (graceful if PG down)
    db.ensure_schema(config)

    sessions = scan_sessions(config, session_id=opts.session_id)
    scored = score_all(sessions)

    # Upsert each session into DB
    upserted = 0
    for meta, score in scored:
        if db.upsert_session(config, meta, score):
            upserted += 1

    # Warm tier promotion: generate summary + embedding for eligible hot sessions
    warmed = 0
    if opts.summarize:
        from session_archiver.embedding import get_embedding
        from session_archiver.scanner import get_active_session_ids
        from session_archiver.summarizer import generate_summary

        active_ids = get_active_session_ids()
        candidates = db.get_warm_candidates(config)
        for sid, project_path in candidates:
            if sid in active_ids:
                continue
            # Find JSONL path
            from pathlib import Path

            proj_dir = Path(config.projects_dir) / project_path
            jsonl_candidates = list(proj_dir.rglob(f"{sid}.jsonl"))
            if not jsonl_candidates:
                continue
            jsonl_path = jsonl_candidates[0]

            summary = generate_summary(jsonl_path)
            if not summary:
                continue

            db.update_summary(config, sid, summary)
            emb = get_embedding(summary, config.omlx_venv, config.embedding_dim)
            if emb:
                db.upsert_embedding(config, sid, emb)
            db.update_tier(config, sid, "warm")
            warmed += 1

    result = {
        "scanned": len(sessions),
        "upserted": upserted,
        "warmed": warmed,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if opts.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Scanned {len(sessions)} sessions, upserted {upserted} to DB")
        if warmed:
            print(f"Promoted {warmed} sessions to warm (summary + embedding generated)")


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

    # Active session guard — never archive sessions with a live PID
    from session_archiver.scanner import get_active_session_ids

    active_ids = get_active_session_ids()
    if active_ids:
        logger.info("active_sessions_protected", count=len(active_ids))

    # Filter candidates: score > threshold, age > min days, not active
    min_age = config.archive_min_age_days
    now = datetime.now(UTC)
    candidates = []
    for meta, score in scored:
        if meta.session_id in active_ids:
            continue
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

    # Generate summaries if requested (skip for warm sessions — they already have one)
    summaries: dict[str, str | None] = {}
    if opts.summarize and not dry_run:
        from session_archiver.summarizer import generate_summary

        for meta, _ in candidates:
            # Check if warm session already has summary in DB
            existing = db.get_session(config, meta.session_id)
            if existing and existing.summary:
                summaries[meta.session_id] = existing.summary
                continue
            if meta.jsonl_path.exists():
                summaries[meta.session_id] = generate_summary(meta.jsonl_path)

    # Archive
    results = archive_batch(config, candidates, summaries=summaries, dry_run=dry_run)

    # Generate embeddings if requested
    # Save summaries to DB (regardless of embedding success)
    if not dry_run and summaries:
        for sid, summary in summaries.items():
            if summary:
                db.update_summary(config, sid, summary)

    # Generate embeddings from summaries
    if opts.embed and not dry_run and summaries:
        from session_archiver.embedding import get_embedding

        for sid, summary in summaries.items():
            if summary:
                emb = get_embedding(summary, config.omlx_venv, config.embedding_dim)
                if emb:
                    db.upsert_embedding(config, sid, emb)

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
            "warm_count": stats.warm_count,
            "warm_size_mb": round(stats.warm_size / 1024 / 1024, 1),
            "cold_count": stats.cold_count,
            "cold_original_mb": round(stats.cold_original_size / 1024 / 1024, 1),
            "cold_compressed_mb": round(stats.cold_compressed_size / 1024 / 1024, 1),
            "frozen_count": stats.frozen_count,
            "frozen_original_mb": round(stats.frozen_original_size / 1024 / 1024, 1),
            "frozen_compressed_mb": round(stats.frozen_compressed_size / 1024 / 1024, 1),
            "total_saved_mb": round(stats.total_saved / 1024 / 1024, 1),
            "compression_ratio": f"{stats.compression_ratio:.1%}"
            if stats.compression_ratio
            else "N/A",
            "db_status": "online",
        }

    if opts.json:
        print(json.dumps(result, indent=2))
    else:
        from session_archiver.scanner import get_active_session_ids

        active_count = len(get_active_session_ids())
        print("Session Archive Status")
        print("=" * 48)
        print(
            f"  Hot:    {result.get('hot_count', 0):>5} sessions ({result.get('hot_size_mb', 0)} MB)"
        )
        print(
            f"  Warm:   {result.get('warm_count', 0):>5} sessions ({result.get('warm_size_mb', 0)} MB) — indexed"
        )
        if "cold_original_mb" in result:
            print(
                f"  Cold:   {result.get('cold_count', 0):>5} sessions "
                f"({result.get('cold_original_mb', 0)} MB "
                f"→ {result.get('cold_compressed_mb', 0)} MB)"
            )
        else:
            print(
                f"  Cold:   {result.get('cold_count', 0):>5} archives "
                f"({result.get('cold_size_mb', 0)} MB)"
            )
        print(f"  Frozen: {result.get('frozen_count', 0):>5} sessions (S3)")
        print("-" * 48)
        if "total_saved_mb" in result:
            print(
                f"  Saved:  {result.get('total_saved_mb', 0)} MB "
                f"({result.get('compression_ratio', 'N/A')})"
            )
        print(f"  Active: {active_count} sessions (protected)")
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


def cmd_freeze(args: list[str]) -> None:
    """Freeze eligible cold sessions to RustFS (S3)."""
    parser = argparse.ArgumentParser(description="Freeze cold sessions to S3")
    parser.add_argument(
        "--execute", action="store_true", help="Actually freeze (default is dry-run)"
    )
    parser.add_argument("--session-id", help="Freeze a specific session by ID")
    parser.add_argument(
        "--min-days",
        type=int,
        default=None,
        help="Minimum days in cold tier (default from config)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()
    if opts.min_days is not None:
        config.freeze_min_cold_days = opts.min_days
    dry_run = not opts.execute

    from session_archiver.freezer import freeze_eligible, freeze_session

    if opts.session_id:
        result = freeze_session(config, opts.session_id, dry_run=dry_run)
        results = [result] if result else []
    else:
        results = freeze_eligible(config, dry_run=dry_run)

    output = {
        "mode": "dry-run" if dry_run else "execute",
        "min_cold_days": config.freeze_min_cold_days,
        "frozen": len(results),
    }

    if opts.json:
        output["details"] = results
        print(json.dumps(output, indent=2))
    else:
        mode_label = "[DRY RUN] " if dry_run else ""
        print(f"{mode_label}Freeze candidates processed: {len(results)}")
        for r in results:
            sid = r["session_id"][:12]
            size_mb = round(r.get("size_bytes", 0) / 1024 / 1024, 2)
            s3 = r.get("s3_uri", "")
            print(f"  {sid}  {size_mb} MB  -> {s3}")
        if dry_run and results:
            print("\nTo execute: session-archiver freeze --execute")


def cmd_info(args: list[str]) -> None:
    """Display session metadata without thawing."""
    parser = argparse.ArgumentParser(description="Session info")
    parser.add_argument("session_id", help="Full or partial session ID (min 8 chars)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()

    from session_archiver import db

    record = db.get_session(config, opts.session_id)
    if record is None:
        print(f"Session not found: {opts.session_id}", file=sys.stderr)
        sys.exit(1)

    # Also fetch reflection if available
    reflection = db.get_reflection(config, record.session_id)

    info = {
        "session_id": record.session_id,
        "project_path": record.project_path,
        "tier": record.tier,
        "file_size_bytes": record.file_size_bytes,
        "file_size_mb": round(record.file_size_bytes / 1024 / 1024, 2),
        "event_count": record.event_count,
        "turn_count": record.turn_count,
        "first_timestamp": record.first_timestamp,
        "last_timestamp": record.last_timestamp,
        "claude_version": record.claude_version,
        "git_branch": record.git_branch,
        "cwd": record.cwd,
        "score": record.score,
        "archive_path": record.archive_path,
        "archive_type": record.archive_type,
        "compressed_size": record.compressed_size,
        "compression_ratio": record.compression_ratio,
        "archived_at": record.archived_at,
        "thawed_at": record.thawed_at,
        "thaw_count": record.thaw_count,
        "summary": record.summary,
        "scanned_at": record.scanned_at,
        "updated_at": record.updated_at,
    }

    if reflection:
        info["reflection"] = {
            "outcome": reflection.get("outcome"),
            "quality_score": reflection.get("quality_score"),
            "total_tokens": reflection.get("total_tokens"),
            "tool_success_rate": reflection.get("tool_success_rate"),
            "duration_secs": reflection.get("duration_secs"),
        }

    if opts.json:
        print(json.dumps(info, indent=2))
    else:
        tier_label = {"hot": "Hot", "warm": "Warm", "cold": "Cold", "frozen": "Frozen (S3)"}.get(
            record.tier, record.tier
        )
        print(f"Session: {record.session_id}")
        print(f"  Project:  {record.project_path}")
        print(f"  Tier:     {tier_label}")
        print(f"  Size:     {info['file_size_mb']} MB ({record.file_size_bytes:,} bytes)")
        print(f"  Events:   {record.event_count}  Turns: {record.turn_count}")
        print(f"  Score:    {record.score:.1f}")
        if record.first_timestamp:
            print(f"  First:    {record.first_timestamp}")
        if record.last_timestamp:
            print(f"  Last:     {record.last_timestamp}")
        if record.claude_version:
            print(f"  Claude:   {record.claude_version}")
        if record.git_branch:
            print(f"  Branch:   {record.git_branch}")
        if record.cwd:
            print(f"  CWD:      {record.cwd}")
        if record.archive_path:
            print(f"  Archive:  {record.archive_path}")
        if record.compressed_size:
            ratio = f" ({record.compression_ratio:.1%})" if record.compression_ratio else ""
            print(f"  Compressed: {record.compressed_size:,} bytes{ratio}")
        if record.archived_at:
            print(f"  Archived: {record.archived_at}")
        if record.thaw_count > 0:
            print(f"  Thawed:   {record.thaw_count}x (last: {record.thawed_at})")
        if record.summary:
            print(f"  Summary:  {record.summary[:100]}")
        if reflection:
            print(
                f"  Reflection: {reflection.get('outcome', '?')} "
                f"(quality={reflection.get('quality_score', 0):.1f}, "
                f"tokens={reflection.get('total_tokens', 0):,})"
            )


def cmd_purge_trivial(args: list[str]) -> None:
    """Purge trivially empty / command-only sessions.

    Identifies sessions that are clearly not worth keeping:
    - File size < threshold (default 3 KB)
    - DB quality_score < 0.15 AND outcome = 'failure'
    - Older than min-age-days (default 3)

    Default is dry-run — pass --execute to actually delete.
    """
    parser = argparse.ArgumentParser(description="Purge trivial sessions")
    parser.add_argument(
        "--execute", action="store_true", help="Actually delete (default is dry-run)"
    )
    parser.add_argument(
        "--threshold-kb",
        type=int,
        default=3,
        help="File size threshold in KB (default 3)",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=3,
        help="Only purge sessions older than N days (default 3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt (for scheduled jobs)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    opts = parser.parse_args(args)

    config = load_config()
    dry_run = not opts.execute
    threshold_bytes = opts.threshold_kb * 1024
    now = datetime.now(UTC)

    from session_archiver.scanner import get_active_session_ids

    active_ids = get_active_session_ids()

    # --- Pass 1: File-based scan (< threshold KB) ---
    candidates: list[dict] = []
    projects_dir = Path(config.projects_dir).expanduser()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            sid = jsonl.stem
            if sid in active_ids:
                continue
            size = jsonl.stat().st_size
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=UTC)
            age_days = (now - mtime).total_seconds() / 86400
            if age_days < opts.min_age_days:
                continue
            if size < threshold_bytes:
                candidates.append({
                    "session_id": sid,
                    "reason": f"file_size={size}B < {opts.threshold_kb}KB",
                    "size_bytes": size,
                    "age_days": round(age_days, 1),
                    "project_dir": str(project_dir),
                })

    # --- Pass 2: DB-based scan (low quality score) ---
    try:
        from session_archiver import db

        low_quality = db.query_low_quality_sessions(config, max_score=0.15)
        for row in low_quality:
            sid = row["session_id"]
            if sid in active_ids:
                continue
            # Check age
            age_days_val = row.get("age_days", 0)
            if age_days_val < opts.min_age_days:
                continue
            # Avoid duplicates
            if any(c["session_id"] == sid for c in candidates):
                continue
            # Find the JSONL file
            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                jsonl = project_dir / f"{sid}.jsonl"
                if jsonl.exists():
                    candidates.append({
                        "session_id": sid,
                        "reason": f"quality={row.get('quality_score', 0):.2f}, outcome={row.get('outcome', '?')}",
                        "size_bytes": jsonl.stat().st_size,
                        "age_days": round(age_days_val, 1),
                        "project_dir": str(project_dir),
                    })
                    break
    except Exception as e:
        logger.warning("db_scan_skipped", error=str(e))

    if not candidates:
        msg = "No trivial sessions found"
        if opts.json:
            print(json.dumps({"candidates": 0, "message": msg}))
        else:
            print(msg)
        return

    # Confirmation
    if not dry_run and not opts.force:
        print(f"About to DELETE {len(candidates)} sessions:")
        for c in candidates[:10]:
            print(f"  {c['session_id'][:12]}  {c['size_bytes']:>6,}B  {c['reason']}")
        if len(candidates) > 10:
            print(f"  ... and {len(candidates) - 10} more")
        resp = input("\nProceed? [y/N] ")
        if resp.lower() != "y":
            print("Aborted.")
            return

    # Execute or dry-run
    deleted = 0
    freed_bytes = 0
    for c in candidates:
        project_dir = Path(c["project_dir"])
        jsonl = project_dir / f"{c['session_id']}.jsonl"
        uuid_dir = project_dir / c["session_id"]

        if not dry_run:
            if jsonl.exists():
                freed_bytes += jsonl.stat().st_size
                jsonl.unlink()
            if uuid_dir.is_dir():
                for f in uuid_dir.rglob("*"):
                    if f.is_file():
                        freed_bytes += f.stat().st_size
                shutil.rmtree(uuid_dir)
            # Clean DB records
            try:
                from session_archiver import db as _db

                _db.delete_session(config, c["session_id"])
            except Exception:
                pass
            deleted += 1
        else:
            freed_bytes += c["size_bytes"]
            deleted += 1

    result = {
        "mode": "dry-run" if dry_run else "execute",
        "candidates": len(candidates),
        "deleted": deleted,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
    }

    if opts.json:
        result["details"] = candidates
        print(json.dumps(result, indent=2))
    else:
        mode_label = "[DRY RUN] " if dry_run else ""
        print(f"{mode_label}Purged {deleted} trivial sessions, freed {result['freed_mb']} MB")
        if dry_run:
            print("\nTo execute: session-archiver purge-trivial --execute")
