#!/usr/bin/env python3
"""ws_ios_simruntime_cleanup.py — Keep only newest iOS Simulator runtime.

Triggered by: macOS / iOS upgrade → `xcodebuild -downloadPlatform iOS` pulls a
new runtime; old ones linger and accumulate ~8.5 GB each. We delete:
  1. All `Unusable` runtimes (e.g. partial-fetched duplicates after upgrade)
  2. All non-newest `Ready` runtimes (keep latest version + UUID only)

Schedule: weekly Sunday 03:00 (manifest.json — ws-ios-simruntime-cleanup)

User policy (2026-05-16): "每次安裝新的，舊的確定無用就可以刪掉"
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime


def log(msg: str) -> None:
    print(f"[ios-simruntime-cleanup] {datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def list_runtimes() -> list[dict]:
    """Returns list of {version, uuid, state, kind}."""
    r = subprocess.run(
        ["xcrun", "simctl", "runtime", "list", "-v"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log(f"WARN: simctl runtime list failed: {r.stderr[:200]}")
        return []

    runtimes = []
    current = None
    for line in r.stdout.splitlines():
        m = re.match(r"^(iOS|tvOS|watchOS|visionOS) ([\d.]+) \(\w+\) - ([A-F0-9-]+)$", line.strip())
        if m:
            if current:
                runtimes.append(current)
            current = {
                "platform": m.group(1),
                "version": m.group(2),
                "uuid": m.group(3),
                "state": None,
            }
        elif current and line.strip().startswith("State:"):
            current["state"] = line.split(":", 1)[1].strip()
    if current:
        runtimes.append(current)
    return runtimes


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def delete_runtime(uuid: str) -> bool:
    r = subprocess.run(
        ["xcrun", "simctl", "runtime", "delete", uuid],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return r.returncode == 0


def main() -> int:
    runtimes = list_runtimes()
    if not runtimes:
        log("no runtimes found, nothing to do")
        return 0

    # Only manage iOS (leave watchOS/tvOS/visionOS alone — small + rarely
    # touched).
    ios = [r for r in runtimes if r["platform"] == "iOS"]
    log(f"found {len(ios)} iOS runtimes")

    if not ios:
        return 0

    # Pick keeper: highest version, prefer Ready over Unusable
    ios.sort(key=lambda r: (version_tuple(r["version"]), r["state"] == "Ready"), reverse=True)
    keeper = next((r for r in ios if r["state"] == "Ready"), ios[0])
    log(f"keep: iOS {keeper['version']} ({keeper['uuid']}) state={keeper['state']}")

    deleted, failed = [], []
    for r in ios:
        if r["uuid"] == keeper["uuid"]:
            continue
        reason = "Unusable" if r["state"] and "Unusable" in r["state"] else "older"
        log(f"delete: iOS {r['version']} ({r['uuid']}) — {reason}")
        if delete_runtime(r["uuid"]):
            deleted.append(r)
        else:
            failed.append(r)

    log(f"summary: kept=1 deleted={len(deleted)} failed={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
