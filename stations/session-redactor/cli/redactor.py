#!/Users/joneshong/.local/bin/python3
"""Session Redactor CLI — detect and redact sensitive data in Claude transcripts.

Usage:
    redactor redact <file>            Redact a single .jsonl file
    redactor sweep                    Full sweep of all projects
    redactor status                   Show aggregate stats
    redactor history [--limit N]      Recent processing records
    redactor patterns                 List all detection patterns
    redactor test <text>              Test redaction on arbitrary text

Flags:
    --json                            Output as JSON (machine-readable)

Examples:
    redactor sweep --json
    redactor test "sk-ant-api03-secretkey123456789abc"
    redactor history --limit 5
"""

import argparse
import json
import os
import sys

# Allow importing from workshop package regardless of PYTHONPATH
_script_dir = os.path.dirname(os.path.abspath(__file__))
_workshop_libs = os.path.join(_script_dir, "..", "..", "libs", "python", "src")
if os.path.isdir(_workshop_libs) and _workshop_libs not in sys.path:
    sys.path.insert(0, _workshop_libs)

from workshop.clients.session_redactor import SessionRedactorClient  # noqa: E402


def _print(data, as_json: bool) -> None:
    """Print data as JSON or human-readable."""
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    if isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                print("  ---")
                for k, v in item.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {item}")
    else:
        print(data)


def cmd_redact(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    file_path = args.file
    if not os.path.isfile(file_path):
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    result = client.redact_file(file_path, trigger="manual")

    if args.json:
        _print(result.to_dict(), True)
        return

    if result.error:
        print(f"  ERROR: {result.error}")
    elif result.skipped:
        print(f"  SKIPPED (already clean or non-.jsonl): {result.file_path}")
    elif result.changed:
        print(f"  REDACTED: {result.file_path}")
        print(f"    redactions: {result.redactions}")
        print(f"    categories: {result.categories}")
    else:
        print(f"  CLEAN (no secrets found): {result.file_path}")
        print("    scanned lines in file")


def cmd_sweep(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    print("Running full sweep...", file=sys.stderr)
    summary = client.full_sweep(trigger="sweep")

    if args.json:
        _print(summary, True)
        return

    print(f"  files_processed : {summary['files_processed']}")
    print(f"  files_skipped   : {summary['files_skipped']}")
    print(f"  total_redactions: {summary['total_redactions']}")
    print(f"  errors          : {summary['errors']}")
    print(f"  swept_at        : {summary['swept_at']}")


def cmd_status(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    stats = client.get_stats()

    if args.json:
        _print(stats, True)
        return

    print("Session Redactor Status")
    print(f"  total_files      : {stats['total_files']}")
    print(f"  total_redactions : {stats['total_redactions']}")
    print(f"  last_processed_at: {stats['last_processed_at'] or 'never'}")
    print(f"  db_path          : {client.db_path}")
    print(f"  projects_dir     : {client.projects_dir}")


def cmd_history(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    limit = args.limit
    records = client.get_history(limit=limit)

    if args.json:
        _print(records, True)
        return

    if not records:
        print("  No processing records found.")
        return

    print(f"Last {len(records)} records (most recent first):")
    for r in records:
        changed_marker = "*" if r.get("redactions", 0) > 0 else " "
        print(
            f"  [{changed_marker}] {r['processed_at']}  "
            f"redactions={r['redactions']}  "
            f"trigger={r['trigger']}  "
            f"{r['file_path']}"
        )


def cmd_patterns(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    patterns = client.list_patterns()

    if args.json:
        _print(patterns, True)
        return

    print(f"Detection Patterns ({len(patterns)} total):")
    current_cat = None
    for p in patterns:
        if p["category"] != current_cat:
            current_cat = p["category"]
            print(f"\n  [{current_cat}]")
        print(f"    {p['name']}")


def cmd_test(args: argparse.Namespace, client: SessionRedactorClient) -> None:
    text = args.text
    result = client.redact_text(text)

    if args.json:
        _print(result, True)
        return

    print(f"Input  : {text}")
    print(f"Output : {result['text']}")
    print(f"Redactions: {result['redactions']}")
    if result["categories"]:
        print(f"Categories: {result['categories']}")
    else:
        print("Categories: (none — no matches)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="redactor",
        description="Session Redactor — detect and redact sensitive data in Claude transcripts",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database path (overrides REDACTOR_DB_PATH env)",
    )
    parser.add_argument(
        "--projects-dir",
        default=None,
        help="Claude projects directory (overrides REDACTOR_PROJECTS_DIR env)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # redact
    redact_p = subparsers.add_parser("redact", help="Redact a single .jsonl file")
    redact_p.add_argument("file", help="Path to .jsonl file")

    # sweep
    subparsers.add_parser("sweep", help="Full sweep of all project transcripts")

    # status
    subparsers.add_parser("status", help="Show aggregate stats")

    # history
    history_p = subparsers.add_parser("history", help="Recent processing records")
    history_p.add_argument(
        "--limit", "-n", type=int, default=30, help="Max records to show (default: 30)"
    )

    # patterns
    subparsers.add_parser("patterns", help="List all detection patterns")

    # test
    test_p = subparsers.add_parser("test", help="Test redaction on arbitrary text")
    test_p.add_argument("text", help="Text to test redaction on")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    client = SessionRedactorClient(
        db_path=args.db_path,
        projects_dir=args.projects_dir,
    )

    dispatch = {
        "redact": cmd_redact,
        "sweep": cmd_sweep,
        "status": cmd_status,
        "history": cmd_history,
        "patterns": cmd_patterns,
        "test": cmd_test,
    }

    try:
        dispatch[args.command](args, client)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
