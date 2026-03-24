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
    freeze     Freeze cold sessions to S3 (dry-run by default)
    info       Display session metadata without thawing
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

# ---------------------------------------------------------------------------
# Log rotation setup — structlog routed through stdlib for rotating file support
# ---------------------------------------------------------------------------
_LOG_DIR = Path.home() / ".claude" / "data" / "session-archiver"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "run.log"

_pre_chain = [
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
]

structlog.configure(
    processors=_pre_chain + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

_formatter = structlog.stdlib.ProcessorFormatter(
    processor=structlog.dev.ConsoleRenderer(),
    foreign_pre_chain=_pre_chain,
)

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)

_file_handler = RotatingFileHandler(
    _LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)
_root_logger.addHandler(_file_handler)

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(_formatter)
_root_logger.addHandler(_stderr_handler)

from session_archiver.cli import (
    cmd_archive,
    cmd_freeze,
    cmd_info,
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
    "freeze": cmd_freeze,
    "thaw": cmd_thaw,
    "status": cmd_status,
    "search": cmd_search,
    "info": cmd_info,
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
