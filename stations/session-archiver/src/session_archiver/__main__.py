#!/usr/bin/env python3
"""Session Archiver — CLI entry point.

Usage:
    uv run python -m session_archiver <command>
    session-archiver <command>

Commands:
    scan       Scan all sessions and update DB index
    score      Display session scores
    archive    Archive sessions (dry-run by default, --execute to run)
    thaw       Restore an archived session
    status     Show archive statistics
    search     Search sessions by summary (semantic + ILIKE fallback)
"""

from __future__ import annotations

import sys

import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

from session_archiver.cli import (
    cmd_archive,
    cmd_scan,
    cmd_score,
    cmd_search,
    cmd_status,
    cmd_thaw,
)

COMMANDS = {
    "scan": cmd_scan,
    "score": cmd_score,
    "archive": cmd_archive,
    "thaw": cmd_thaw,
    "status": cmd_status,
    "search": cmd_search,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Session Archiver v0.1.0 — Cold/hot tiered compression")
        print()
        print("Commands:")
        print("  scan       Scan all sessions, update DB index")
        print("  score      Display session scores (table format)")
        print("  archive    Archive sessions (dry-run default, --execute to run)")
        print("  thaw       Restore an archived session")
        print("  status     Show archive statistics")
        print("  search     Search by summary (semantic → ILIKE fallback)")
        print()
        print("Usage: session-archiver <command> [options]")
        print("       uv run python -m session_archiver <command> [options]")
        sys.exit(0)

    if sys.argv[1] == "--version":
        from session_archiver import __version__

        print(f"session-archiver {__version__}")
        sys.exit(0)

    cmd_name = sys.argv[1]
    if cmd_name not in COMMANDS:
        print(f"Unknown command: {cmd_name}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    COMMANDS[cmd_name](sys.argv[2:])


if __name__ == "__main__":
    main()
