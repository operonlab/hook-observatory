#!/Users/joneshong/.local/bin/python3
"""archiver -- Workshop Session Archiver CLI.

Usage:
    archiver scan                                # scan sessions, update DB
    archiver score [--top N]                     # show session scores
    archiver archive [--execute] [--threshold N] [--summarize] [--embed]
    archiver thaw <session_id>                   # restore archived session
    archiver status                              # archive statistics
    archiver search <query> [--limit N]          # semantic search

Symlink: ln -sf ~/workshop/stations/session-archiver-cli/archiver.py ~/.local/bin/archiver
"""

import argparse
import json
import sys

from workshop.clients.session_archiver import SessionArchiverClient, SessionArchiverError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


# ======================== Commands ========================


def cmd_scan(args):
    client = SessionArchiverClient()
    try:
        result = client.scan()
        if args.json:
            _json_out(result, True)
        else:
            scanned = result.get("scanned", 0)
            upserted = result.get("upserted", 0)
            print(f"Scanned {scanned} sessions, upserted {upserted} to DB")
    except SessionArchiverError as e:
        _err(e)


def cmd_score(args):
    client = SessionArchiverClient()
    try:
        result = client.score(top=args.top)
        if args.json:
            _json_out(result, True)
        else:
            if isinstance(result, list):
                rows = result
            else:
                rows = result if isinstance(result, list) else [result]
            for r in rows:
                sid = r.get("session_id", "?")
                size = r.get("size_mb", 0)
                score = r.get("score", 0)
                print(f"  {sid}  {size:>7.1f} MB  score={score:.1f}")
            print(f"\nTotal: {len(rows)} sessions")
    except SessionArchiverError as e:
        _err(e)


def cmd_archive(args):
    client = SessionArchiverClient()
    try:
        result = client.archive(
            execute=args.execute,
            threshold=args.threshold,
            summarize=args.summarize,
            embed=args.embed,
        )
        if args.json:
            _json_out(result, True)
        else:
            mode = result.get("mode", "?")
            candidates = result.get("candidates", 0)
            archived = result.get("archived", 0)
            saved = result.get("total_saved_mb", 0)
            print(f"[{mode}] Candidates: {candidates}, Archived: {archived}")
            if mode == "execute" and saved:
                print(f"Total saved: {saved} MB")
            if mode == "dry-run":
                print("\nTo execute: archiver archive --execute")
    except SessionArchiverError as e:
        _err(e)


def cmd_thaw(args):
    client = SessionArchiverClient()
    try:
        result = client.thaw(args.session_id)
        if args.json:
            _json_out(result, True)
        else:
            output = result.get("output", "")
            if output:
                print(output)
            else:
                print(f"Session {args.session_id} restored.")
    except SessionArchiverError as e:
        _err(e)


def cmd_status(args):
    client = SessionArchiverClient()
    try:
        result = client.status()
        if args.json:
            _json_out(result, True)
        else:
            print("Session Archive Status")
            print("=" * 40)
            print(
                f"  Hot:    {result.get('hot_count', 0)} sessions ({result.get('hot_size_mb', 0)} MB)"
            )
            if "cold_original_mb" in result:
                print(
                    f"  Cold:   {result.get('cold_count', 0)} sessions "
                    f"({result.get('cold_original_mb', 0)} MB -> {result.get('cold_compressed_mb', 0)} MB)"
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
    except SessionArchiverError as e:
        _err(e)


def cmd_search(args):
    client = SessionArchiverClient()
    try:
        result = client.search(args.query, limit=args.limit)
        if args.json:
            _json_out(result, True)
        else:
            if isinstance(result, list):
                rows = result
            elif isinstance(result, dict) and "raw_output" in result:
                print(result["raw_output"])
                return
            else:
                rows = result if isinstance(result, list) else [result]

            if not rows:
                print(f"No results for: {args.query}")
                return

            print(f"Results for '{args.query}':")
            for r in rows:
                tier = r.get("tier", "?")
                tier_icon = {"hot": "H", "cold": "C", "frozen": "F"}.get(tier, "?")
                sid = r.get("session_id", "?")
                summary = (r.get("summary") or "")[:60]
                print(f"  [{tier_icon}] {sid}  {summary}")
            print(f"\n{len(rows)} result(s)")
    except SessionArchiverError as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="archiver",
        description="Workshop Session Archiver CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Scan sessions, update DB index")
    p_scan.set_defaults(func=cmd_scan)

    # score
    p_score = sub.add_parser("score", help="Display session scores")
    p_score.add_argument("--top", type=int, default=0, help="Show top N only (0 = all)")
    p_score.set_defaults(func=cmd_score)

    # archive
    p_archive = sub.add_parser("archive", help="Archive sessions (dry-run default)")
    p_archive.add_argument("--execute", action="store_true", help="Actually archive")
    p_archive.add_argument("--threshold", type=int, default=None, help="Score threshold")
    p_archive.add_argument("--summarize", action="store_true", help="Generate LLM summaries")
    p_archive.add_argument("--embed", action="store_true", help="Generate embeddings")
    p_archive.set_defaults(func=cmd_archive)

    # thaw
    p_thaw = sub.add_parser("thaw", help="Restore an archived session")
    p_thaw.add_argument("session_id", help="Full or partial session ID (min 8 chars)")
    p_thaw.set_defaults(func=cmd_thaw)

    # status
    p_status = sub.add_parser("status", help="Archive statistics")
    p_status.set_defaults(func=cmd_status)

    # search
    p_search = sub.add_parser("search", help="Search sessions by summary")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
