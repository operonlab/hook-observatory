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

# Use the station's own .venv — it carries sdk_client's transitive deps
# (python-json-logger etc.) which the user-global ~/.local/bin/python3
# can't see because uv-managed pythons are externally-managed.
PYTHON = Path.home() / "workshop" / "stations" / "session-archiver" / ".venv" / "bin" / "python"
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
