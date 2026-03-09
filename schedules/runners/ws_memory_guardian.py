#!/usr/bin/env python3
"""
ws_memory_guardian.py — Every 60s: memory pressure guardian

Runs the memory guardian check from system-monitor station.
Can also be invoked directly: python ws_memory_guardian.py
"""

import sys
from pathlib import Path

# Add system-monitor station to path
STATION_DIR = Path.home() / "workshop" / "stations" / "system-monitor"
sys.path.insert(0, str(STATION_DIR))

from memory_guardian import MemoryGuardian  # noqa: E402


def main():
    guardian = MemoryGuardian()
    result = guardian.run()

    status = result.get("status", "unknown")
    level = result.get("mem_level", "?")

    if status == "acted":
        killed = result.get("total_killed", 0)
        freed = result.get("p1_freed_mb", 0)
        print(f"Guardian acted: level={level} killed={killed} freed≈{freed}MB")
    elif status == "ok":
        print(f"Memory OK (level={level})")
    else:
        print(f"Skip: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    main()
