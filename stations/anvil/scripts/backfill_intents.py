#!/Users/joneshong/.local/bin/python3
"""Backfill Anvil intent tracking from Claude Code session transcripts.

Scans all .jsonl files under ~/.claude/projects/, extracts <command-name>
tags from user messages, and POSTs them as intents to the Anvil API.

Usage:
    ./backfill_intents.py
    ./backfill_intents.py --dry-run
    ./backfill_intents.py --since 2026-01-01
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ANVIL_BASE = "http://127.0.0.1:4103/api/anvil"
PROJECTS_ROOT = Path.home() / ".claude" / "projects"

# Known CLI builtins (not skills)
_CLI_BUILTINS = frozenset(
    {
        "clear",
        "exit",
        "context",
        "mcp",
        "login",
        "model",
        "config",
        "help",
        "compact",
        "fast",
        "cost",
        "memory",
        "permissions",
        "agents",
        "skills",
        "terminal-setup",
        "vim",
        "bug",
        "doctor",
        "release-notes",
        "init",
        "review",
        "allowed-tools",
        "listen",
        "status-bar",
        "add-dir",
        "loop",
    }
)

# Test patterns
_TEST_PREFIXES = ("_", "test-")
_TEST_EXACT = {"test-skill", "test-verify", "general-purpose", "commit"}
_TEST_DIGIT = re.compile(r"^skill-\d+$")

_COMMAND_NAME_RE = re.compile(r"<command-name>/([^<]+)</command-name>")


def _is_test(name: str) -> bool:
    if any(name.startswith(p) for p in _TEST_PREFIXES):
        return True
    if name in _TEST_EXACT:
        return True
    if _TEST_DIGIT.match(name):
        return True
    return False


def _http_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check_anvil_alive() -> bool:
    try:
        _http_get(f"{ANVIL_BASE.replace('/api/anvil', '')}/api/anvil/health")
        return True
    except Exception:
        return False


def extract_intents(path: Path, since: datetime | None) -> list[dict]:
    """Parse one .jsonl file and return list of intent dicts."""
    results = []
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                session_id = entry.get("sessionId") or entry.get("session_id")
                if not session_id:
                    continue

                ts_raw = entry.get("timestamp")
                if ts_raw:
                    try:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    except ValueError:
                        ts = file_mtime
                else:
                    ts = file_mtime

                if since and ts < since:
                    continue

                # Only look at user messages
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "user":
                    continue

                content = message.get("content", [])
                if isinstance(content, str):
                    text_blocks = [content]
                elif isinstance(content, list):
                    text_blocks = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                else:
                    continue

                for text in text_blocks:
                    for m in _COMMAND_NAME_RE.finditer(text):
                        skill_name = m.group(1).strip()
                        if skill_name in _CLI_BUILTINS:
                            continue
                        if _is_test(skill_name):
                            continue
                        results.append(
                            {
                                "skill_name": skill_name,
                                "session_id": session_id,
                                "timestamp": ts.isoformat(),
                            }
                        )
    except OSError as exc:
        print(f"  [warn] Cannot read {path}: {exc}", file=sys.stderr)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Anvil intent tracking from Claude Code session transcripts."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", metavar="YYYY-MM-DD")
    args = parser.parse_args()

    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        except ValueError:
            print(f"[error] Invalid --since date: {args.since!r}", file=sys.stderr)
            sys.exit(1)

    if not args.dry_run:
        if not check_anvil_alive():
            print("[error] Anvil API not reachable. Use --dry-run.", file=sys.stderr)
            sys.exit(1)

    all_jsonl = sorted(PROJECTS_ROOT.rglob("*.jsonl"))
    total_sessions = len(all_jsonl)

    if total_sessions == 0:
        print(f"[info] No .jsonl files found under {PROJECTS_ROOT}")
        return

    print(
        f"[info] Scanning {total_sessions} session file(s)"
        + (f" (since {args.since})" if args.since else "")
        + (" [DRY RUN]" if args.dry_run else "")
    )

    total_found = 0
    total_posted = 0

    for idx, jsonl_path in enumerate(all_jsonl, 1):
        intents = extract_intents(jsonl_path, since_dt)
        total_found += len(intents)

        if not args.dry_run:
            for intent in intents:
                payload = {
                    "skill_name": intent["skill_name"],
                    "session_id": intent["session_id"],
                    "timestamp": intent["timestamp"],
                }
                try:
                    _http_post(f"{ANVIL_BASE}/intents", payload)
                    total_posted += 1
                except urllib.error.URLError as exc:
                    print(f"[error] POST failed: {exc}", file=sys.stderr)
                    print("[error] Anvil became unreachable. Aborting.", file=sys.stderr)
                    sys.exit(1)

        if idx % 50 == 0 or idx == total_sessions:
            if args.dry_run:
                print(f"Processed {idx}/{total_sessions}, found {total_found} intents [DRY RUN]")
            else:
                print(
                    f"Processed {idx}/{total_sessions}, found {total_found}, posted {total_posted}"
                )

    print()
    if args.dry_run:
        print(f"[done] DRY RUN: {total_found} intents across {total_sessions} sessions.")
    else:
        print(f"[done] Posted: {total_posted} | Found: {total_found} | Sessions: {total_sessions}")


if __name__ == "__main__":
    main()
