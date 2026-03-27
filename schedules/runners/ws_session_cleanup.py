#!/usr/bin/env python3
"""Weekly trivial session cleanup.

Scheduled via Cronicle: every Sunday 4AM.
Calls session-archiver purge-trivial with --execute --force --min-age-days 7.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PYTHON = Path.home() / ".local" / "bin" / "python3"
ARCHIVER = Path.home() / "workshop" / "stations" / "session-archiver" / "src"


def main() -> None:
    result = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "session_archiver",
            "purge-trivial",
            "--execute",
            "--force",
            "--min-age-days",
            "7",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ARCHIVER),
        timeout=120,
    )

    if result.returncode != 0:
        print(f"[ERROR] purge-trivial failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = {"raw": result.stdout}

    deleted = data.get("deleted", 0)
    freed = data.get("freed_mb", 0)
    print(f"Session cleanup: deleted {deleted} trivial sessions, freed {freed} MB")

    if deleted > 0:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
