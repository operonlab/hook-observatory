#!/Users/joneshong/.local/bin/python3
"""Backfill Anvil telemetry from Claude Code session transcripts.

Scans all .jsonl files under ~/.claude/projects/, extracts Skill tool_use
invocations, deduplicates against existing Anvil records, and POSTs new
entries to the Anvil API.

Usage:
    ./backfill_transcripts.py
    ./backfill_transcripts.py --dry-run
    ./backfill_transcripts.py --since 2026-01-01
    ./backfill_transcripts.py --dry-run --since 2026-03-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ANVIL_BASE = "http://127.0.0.1:4103/api/anvil"
PROJECTS_ROOT = Path.home() / ".claude" / "projects"

# Tool registry for CLI/MCP backfill
_REGISTRY_PATH = (
    Path.home() / "workshop" / "stations" / "hook-observatory" / "handlers" / "tool_registry.json"
)
_MCP_REGISTRY: dict[str, str] = {}
_CLI_REGISTRY: dict[str, str] = {}
_MCP_PROXY_TOOLS = {
    "mcp__mcpproxy__call_tool_read",
    "mcp__mcpproxy__call_tool_write",
    "mcp__mcpproxy__call_tool_destructive",
}

try:
    with open(_REGISTRY_PATH) as _f:
        _reg = json.load(_f)
    _MCP_REGISTRY = _reg.get("mcp_servers", {})
    _CLI_REGISTRY = _reg.get("cli_commands", {})
except (OSError, json.JSONDecodeError):
    pass


# ---------------------------------------------------------------------------
# HTTP helpers (urllib only, no external deps)
# ---------------------------------------------------------------------------


def _http_get(url: str) -> dict:
    """GET JSON from url; raises urllib.error.URLError on failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _http_post(url: str, payload: dict) -> dict:
    """POST JSON payload; returns parsed response dict."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check_anvil_alive() -> bool:
    """Return True if Anvil health endpoint responds."""
    try:
        _http_get(f"{ANVIL_BASE.replace('/api/anvil', '')}/api/anvil/health")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------


def extract_skill_calls(path: Path, since: datetime | None) -> list[dict]:
    """Parse one .jsonl file and return list of skill invocation dicts.

    Each dict has: skill_name, session_id, timestamp (ISO str), args
    """
    results = []

    # Fallback timestamp: file mtime
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _lineno, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Extract session_id
                session_id = entry.get("sessionId") or entry.get("session_id")
                if not session_id:
                    continue

                # Extract timestamp
                ts_raw = entry.get("timestamp")
                if ts_raw:
                    try:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    except ValueError:
                        ts = file_mtime
                else:
                    ts = file_mtime

                # Apply --since filter
                if since and ts < since:
                    continue

                # Navigate: entry.message.content[]
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue

                content = message.get("content")
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue

                    block_name = block.get("name", "")
                    inp = block.get("input", {})
                    tool_use_id = block.get("id", "")

                    # --- Channel 1: Skill tool calls ---
                    if block_name == "Skill":
                        skill_name = inp.get("skill")
                        if not skill_name:
                            continue
                        results.append(
                            {
                                "skill_name": skill_name,
                                "session_id": session_id,
                                "timestamp": ts.isoformat(),
                                "args": inp.get("args", ""),
                                "tool_use_id": tool_use_id,
                                "category": "skill",
                            }
                        )

                    # --- Channel 2: MCP proxy calls ---
                    elif block_name in _MCP_PROXY_TOOLS:
                        mcp_name = inp.get("name", "")
                        if ":" not in mcp_name:
                            continue
                        server, tool = mcp_name.split(":", 1)
                        station = _MCP_REGISTRY.get(server)
                        if not station:
                            continue
                        results.append(
                            {
                                "skill_name": station,
                                "session_id": session_id,
                                "timestamp": ts.isoformat(),
                                "args": "",
                                "tool_use_id": tool_use_id,
                                "category": "mcp",
                                "mcp_tool": tool,
                                "mcp_server": server,
                            }
                        )

                    # --- Channel 3: CLI commands ---
                    elif block_name == "Bash":
                        cmd = inp.get("command", "").strip()
                        if not cmd:
                            continue
                        tokens = cmd.split(None, 2)
                        if not tokens:
                            continue
                        binary = os.path.basename(tokens[0])
                        station = _CLI_REGISTRY.get(binary)
                        if not station:
                            continue
                        results.append(
                            {
                                "skill_name": station,
                                "session_id": session_id,
                                "timestamp": ts.isoformat(),
                                "args": "",
                                "tool_use_id": tool_use_id,
                                "category": "cli",
                                "cli_command": cmd[:200],
                            }
                        )
    except OSError as exc:
        print(f"  [warn] Cannot read {path}: {exc}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Anvil telemetry from Claude Code session transcripts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count invocations without POSTing anything.",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only include sessions with timestamps on or after this date.",
    )
    args = parser.parse_args()

    # Parse --since
    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        except ValueError:
            print(f"[error] Invalid --since date: {args.since!r}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    # Check Anvil is reachable (unless dry-run)
    if not args.dry_run:
        if not check_anvil_alive():
            print(
                "[error] Anvil API is not reachable at http://127.0.0.1:4103. "
                "Start Anvil first or use --dry-run.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Collect all .jsonl files
    all_jsonl = sorted(PROJECTS_ROOT.rglob("*.jsonl"))
    total_sessions = len(all_jsonl)

    if total_sessions == 0:
        print(f"[info] No .jsonl files found under {PROJECTS_ROOT}")
        return

    print(
        f"[info] Scanning {total_sessions} session file(s) under {PROJECTS_ROOT}"
        + (f" (since {args.since})" if args.since else "")
        + (" [DRY RUN]" if args.dry_run else "")
    )

    total_found = 0
    total_posted = 0
    total_skipped = 0
    seen: set[str] = set()

    for idx, jsonl_path in enumerate(all_jsonl, 1):
        calls = extract_skill_calls(jsonl_path, since_dt)
        total_found += len(calls)

        if not args.dry_run:
            for call in calls:
                session_id = call["session_id"]
                skill_name = call["skill_name"]
                tool_use_id = call.get("tool_use_id", "")

                # Deduplicate within this run using tool_use_id
                if tool_use_id:
                    if tool_use_id in seen:
                        total_skipped += 1
                        continue
                    seen.add(tool_use_id)

                category = call.get("category", "skill")
                payload_data: dict = {
                    "args": call.get("args", ""),
                    "source": "backfill",
                }
                if call.get("mcp_tool"):
                    payload_data["tool"] = call["mcp_tool"]
                    payload_data["server"] = call.get("mcp_server", "")
                if call.get("cli_command"):
                    payload_data["command"] = call["cli_command"]

                payload = {
                    "skill_name": skill_name,
                    "session_id": session_id,
                    "tool_use_id": tool_use_id or None,
                    "timestamp": call["timestamp"],
                    "category": category,
                    "success": True,
                    "tool_calls_count": 1,
                    "payload": payload_data,
                }

                try:
                    _http_post(f"{ANVIL_BASE}/invocations", payload)
                    total_posted += 1
                except urllib.error.URLError as exc:
                    print(
                        f"[error] Failed to POST invocation "
                        f"(skill={skill_name}, session={session_id[:8]}...): {exc}",
                        file=sys.stderr,
                    )
                    # Anvil went down mid-run — abort
                    print("[error] Anvil became unreachable. Aborting.", file=sys.stderr)
                    print(
                        f"Progress: Processed {idx}/{total_sessions} sessions, "
                        f"found {total_found} skill calls, "
                        f"posted {total_posted} new, "
                        f"skipped {total_skipped} (already exist)."
                    )
                    sys.exit(1)

        # Progress line every 50 files or at the end
        if idx % 50 == 0 or idx == total_sessions:
            if args.dry_run:
                print(
                    f"Processed {idx}/{total_sessions} sessions, "
                    f"found {total_found} skill calls [DRY RUN — nothing posted]"
                )
            else:
                print(
                    f"Processed {idx}/{total_sessions} sessions, "
                    f"found {total_found} skill calls, "
                    f"posted {total_posted} new, "
                    f"skipped {total_skipped} (already exist)"
                )

    # Final summary
    print()
    if args.dry_run:
        print(
            f"[done] DRY RUN complete. "
            f"Would process {total_found} Skill invocation(s) across "
            f"{total_sessions} session file(s)."
        )
    else:
        print(
            f"[done] Backfill complete. "
            f"Sessions scanned: {total_sessions} | "
            f"Skill calls found: {total_found} | "
            f"Posted: {total_posted} | "
            f"Skipped (dup): {total_skipped}"
        )


if __name__ == "__main__":
    main()
