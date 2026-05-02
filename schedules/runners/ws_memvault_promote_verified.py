#!/usr/bin/env python3
"""
ws_memvault_promote_verified.py — weekly UNVERIFIED→VERIFIED promotion.

Calls memvault.kg_verification.promote_unverified() and writes a summary line
to outputs/memvault/logs/promote_verified.log. First week is dry-run only;
flip MEMVAULT_PROMOTE_VERIFIED_DRY_RUN=0 in env when stats look sane.

Logs: ~/workshop/outputs/memvault/logs/promote_verified.log
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / "workshop" / "outputs" / "memvault" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "promote_verified.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


async def _run() -> int:
    # Defer imports — runner is invoked from a thin shell so the heavy module
    # load only happens when the job fires.
    sys.path.insert(0, str(Path.home() / "workshop" / "core"))
    from src.modules.memvault.kg_verification import promote_unverified
    from src.shared.database import async_session_factory

    dry_run = os.environ.get("MEMVAULT_PROMOTE_VERIFIED_DRY_RUN", "1") != "0"
    space_id = os.environ.get("MEMVAULT_SPACE_ID", "default")

    log(f"Starting promote_unverified (dry_run={dry_run}, space={space_id})")
    async with async_session_factory() as db:
        stats = await promote_unverified(db, space_id=space_id, dry_run=dry_run)
    log(
        f"Done — candidates={stats.candidates_scanned} "
        f"promoted={stats.promoted_count} demoted={stats.demoted_count}"
    )
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_run())
    except Exception as e:  # pragma: no cover — runner-level safety
        log(f"FATAL: {e!r}")
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
