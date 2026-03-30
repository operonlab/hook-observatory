#!/usr/bin/env python3
"""
ws_pw_profile_cleanup.py — Weekly Playwright master profile cache cleanup

Removes browser cache, code cache, GPU cache, and SW cache storage
from the master profile to keep APFS clone times fast (<5s).

Cronicle event: ws-pw-profile-cleanup
Schedule: Every Sunday 04:00
"""

import shutil
from datetime import datetime
from pathlib import Path

MASTER = Path.home() / ".playwright-profiles" / "master" / "Default"
CLEANUP_DIRS = [
    MASTER / "Cache",
    MASTER / "Code Cache",
    MASTER / "GPUCache",
    MASTER / "Service Worker" / "CacheStorage",
]


def main() -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    before = sum(
        sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        for d in CLEANUP_DIRS
        if d.exists()
    )

    for d in CLEANUP_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)

    print(f"[{ts}] pw-profile-cleanup: freed {before / 1024 / 1024:.0f}MB from master profile")


if __name__ == "__main__":
    main()
