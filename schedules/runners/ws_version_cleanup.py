#!/usr/bin/env python3
"""ws_version_cleanup.py — Sweep old versions of self-managed tools.

Policy (2026-05-16, 少爺): "安裝新版直接把舊版砍了" — keep newest only.
若以後需要退回舊版，直接從官網重新下載即可（installer / GitHub release / brew formula）。

Targets:
  1. iOS Simulator runtime  — `xcrun simctl runtime delete` for non-newest +
     Unusable
  2. Claude Code versions   — `~/.local/share/claude/versions/<ver>/` keep only
     the version pointed to by the `claude` symlink
  3. Homebrew old kegs / cache — `brew cleanup -s` (formula + cask + download
     cache)

Schedule: weekly Sunday 02:30 (manifest.json — ws-version-cleanup)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def log(msg: str) -> None:
    print(
        f"[version-cleanup] {datetime.now().strftime('%H:%M:%S')} {msg}",
        flush=True,
    )


# ── iOS Simulator runtime ─────────────────────────────────────────────────────


def _list_ios_runtimes() -> list[dict]:
    r = subprocess.run(
        ["xcrun", "simctl", "runtime", "list", "-v"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log(f"WARN: simctl runtime list failed: {r.stderr[:200]}")
        return []
    runtimes, current = [], None
    for line in r.stdout.splitlines():
        m = re.match(
            r"^(iOS|tvOS|watchOS|visionOS) ([\d.]+) \(\w+\) - ([A-F0-9-]+)$",
            line.strip(),
        )
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


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def cleanup_ios_simulator() -> tuple[int, int]:
    ios = [r for r in _list_ios_runtimes() if r["platform"] == "iOS"]
    if not ios:
        log("iOS Simulator: no runtimes")
        return (0, 0)
    ios.sort(
        key=lambda r: (_ver_tuple(r["version"]), r["state"] == "Ready"),
        reverse=True,
    )
    keeper = next((r for r in ios if r["state"] == "Ready"), ios[0])
    log(f"iOS Simulator: keep {keeper['version']} ({keeper['uuid']}) state={keeper['state']}")
    deleted, failed = 0, 0
    for r in ios:
        if r["uuid"] == keeper["uuid"]:
            continue
        reason = "Unusable" if r["state"] and "Unusable" in r["state"] else "older"
        log(f"iOS Simulator: delete {r['version']} ({r['uuid']}) — {reason}")
        rr = subprocess.run(
            ["xcrun", "simctl", "runtime", "delete", r["uuid"]],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if rr.returncode == 0:
            deleted += 1
        else:
            failed += 1
            log(f"  FAIL: {rr.stderr[:200]}")
    return (deleted, failed)


# ── Claude Code versions ──────────────────────────────────────────────────────


def cleanup_claude_versions() -> tuple[int, int]:
    versions_dir = Path.home() / ".local/share/claude/versions"
    symlink = Path.home() / ".local/bin/claude"
    if not versions_dir.is_dir():
        log("Claude versions: dir not found")
        return (0, 0)
    if not symlink.is_symlink():
        log("Claude versions: ~/.local/bin/claude is not a symlink — skip")
        return (0, 0)
    keeper_name = symlink.resolve().name
    log(f"Claude versions: keep {keeper_name}")
    deleted, failed = 0, 0
    for entry in versions_dir.iterdir():
        if entry.name == keeper_name:
            continue
        log(f"Claude versions: delete {entry.name}")
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            deleted += 1
        except Exception as e:
            failed += 1
            log(f"  FAIL: {e}")
    return (deleted, failed)


# ── Homebrew kegs + cache ─────────────────────────────────────────────────────


def cleanup_homebrew() -> tuple[int, int]:
    brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
    if not Path(brew).exists():
        log("brew: binary not found")
        return (0, 0)
    log("brew cleanup -s --prune=all (older kegs + download cache + casks)")
    rr = subprocess.run(
        [brew, "cleanup", "-s", "--prune=all"],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"},
    )
    for line in rr.stdout.splitlines()[-12:]:
        log(f"  brew: {line}")
    return (1 if rr.returncode == 0 else 0, 0 if rr.returncode == 0 else 1)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    log("=== version cleanup start ===")
    total_deleted, total_failed = 0, 0
    for name, fn in [
        ("iOS Simulator", cleanup_ios_simulator),
        ("Claude versions", cleanup_claude_versions),
        ("Homebrew", cleanup_homebrew),
    ]:
        try:
            d, f = fn()
            total_deleted += d
            total_failed += f
        except Exception as e:
            log(f"{name}: EXCEPTION {e}")
            total_failed += 1
    log(f"=== done: deleted={total_deleted} failed={total_failed} ===")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
