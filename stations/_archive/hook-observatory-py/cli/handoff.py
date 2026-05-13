#!/usr/bin/env python3
"""
Context Relay CLI — handoff session state to a new Claude Code pane.

Commands:
  handoff spawn   — summarise + acquire pane + write handoff + start CC
  handoff write   — summarise + write handoff (manual pane spawn)
  handoff status  — show pending handoffs
  handoff read    — manually read a handoff for a pane
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BASE_URL = os.environ.get("SESSION_CHANNEL_URL", "http://localhost:10101")
_LOCAL_KEY = os.environ.get("SESSION_CHANNEL_KEY", "change-me-in-production")
_HANDOFF_DIR = "/tmp/handoff"  # noqa: S108
_PYTHON = os.path.expanduser("~/.local/bin/python3")

_DEFAULT_ROLES = ["探索可行性", "找潛在風險", "提出替代方案"]
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_PANE_NUM_RE = re.compile(r"^\d+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_tmux() -> None:
    """Exit early if not running inside tmux."""
    if not os.environ.get("TMUX_PANE"):
        print("❌ 必須在 tmux 環境中執行", file=sys.stderr)
        sys.exit(1)


def _pane_id() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    return pane.replace("%", "pane-") if pane else f"cli-{os.getpid()}"


def _pane_num() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    num = pane.replace("%", "") if pane else ""
    return num if _PANE_NUM_RE.match(num) else ""


def _validate_pane_num(raw: str) -> str:
    """Sanitise and validate a pane number. Exits on invalid input (path traversal prevention)."""
    num = raw.replace("pane-", "").replace("%", "")
    if not _PANE_NUM_RE.match(num):
        print(f"❌ Invalid pane identifier: {raw} (must be digits only)", file=sys.stderr)
        sys.exit(1)
    return num


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from terminal output."""
    return _ANSI_RE.sub("", text)


def _capture_context(lines: int = 100) -> str:
    """Capture recent tmux pane content."""
    try:
        r = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _summarise_with_llm(context: str, role: str | None = None) -> str:
    """Use headless Haiku to generate HANDOFF.md format summary."""
    role_hint = f"\nRole perspective: {role}" if role else ""
    prompt = (
        "Summarise this Claude Code session context into a concise handoff document. "
        "Use this exact format (Traditional Chinese for labels, content language matches original):\n\n"
        "## Goal\n<one line>\n\n"
        "## Key Decisions\n<numbered list with WHY>\n\n"
        "## Files Modified\n<path : what changed>\n\n"
        "## Next Steps\n<concrete items with file paths>\n\n"
        "## Important Context\n<anything the next session needs to know>\n\n"
        f"Keep under 50 lines total. Be specific, not vague.{role_hint}\n\n"
        "---\nSession context:\n\n"
        f"{context[-6000:]}"  # Last 6000 chars to stay within Haiku limits
    )

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # Prevent nesting detection
    env["CLAUDE_VOICE"] = "0"

    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception as e:
        print(f"⚠️  LLM summarise failed: {e}", file=sys.stderr)

    # Fallback: strip ANSI and truncate (raw terminal output may contain escape codes)
    clean = _strip_ansi(context[-2000:])
    return f"## Goal\n(auto-summary failed, raw context below)\n\n```\n{clean}\n```"


def _write_to_redis(target_pane: str, markdown: str) -> bool:
    """Write handoff to session-channel. Returns True on success."""
    body = json.dumps(
        {
            "topic": f"handoff:{target_pane}",
            "text": markdown,
            "sender": _pane_id(),
            "priority": "high",
            "tag": "handoff",
        }
    )
    try:
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "-m",
                "3",
                "-X",
                "POST",
                f"{_BASE_URL}/api/messages",
                "-H",
                "Content-Type: application/json",
                "-H",
                f"x-local-key: {_LOCAL_KEY}",
                "-d",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip().startswith("2")  # Accept 2xx
    except Exception:
        return False


def _write_to_file(target_pane_num: str, data: dict) -> None:
    """Write handoff to file fallback."""
    os.makedirs(_HANDOFF_DIR, exist_ok=True)
    path = os.path.join(_HANDOFF_DIR, f"{target_pane_num}.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _allocate_panes(count: int = 1, cwd: str = "") -> list[str]:
    """Allocate tmux panes without starting Claude (Phase 1 of spawn).

    Starts each pane in a plain bash shell so handoff can be written
    before Claude's SessionStart hook fires.
    """
    import shlex

    start_dir = cwd or os.getcwd()
    acquired = []
    for _ in range(count):
        try:
            r = subprocess.run(
                [
                    "tmux",
                    "split-window",
                    "-h",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    f"cd {shlex.quote(start_dir)} && exec bash",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                acquired.append(r.stdout.strip())
        except Exception:
            pass
    return acquired


def _format_for_injection(handoff_md: str, source: str, role: str | None = None) -> str:
    """Format the full markdown that will be injected via SessionStart hook."""
    header = f"[Context Relay] 接續自 {source} 的工作"
    if role:
        header += f"\n**角色**: {role}"
    return f"{header}\n\n{handoff_md}"


def _read_pending_handoffs() -> list[dict]:
    """List all pending handoff files."""
    if not os.path.isdir(_HANDOFF_DIR):
        return []
    results = []
    for fname in os.listdir(_HANDOFF_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_HANDOFF_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            data["_file"] = fname
            results.append(data)
        except Exception:
            pass
    return sorted(results, key=lambda d: d.get("timestamp", 0), reverse=True)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_spawn(args):
    """Summarise context + acquire pane(s) + write handoff + start CC.

    Three-phase execution to eliminate the spawn race condition:
      Phase 1 — Allocate tmux panes (plain bash, Claude NOT started yet)
      Phase 2 — Write handoff to Redis + file for each pane
      Phase 3 — Send 'claude' to each pane (SessionStart fires AFTER handoff is ready)
    """
    _require_tmux()
    count = args.count or 1
    roles = None
    if args.roles:
        roles = [r.strip() for r in args.roles.split(",")]
    elif count > 1:
        roles = _DEFAULT_ROLES[:count]

    source = _pane_id()
    print(f"📋 Capturing context from {source}...")
    context = _capture_context(100)
    if not context:
        print("❌ Cannot capture tmux pane content", file=sys.stderr)
        sys.exit(1)

    print("🤖 Generating handoff summary (Haiku)...")
    handoff_md = _summarise_with_llm(context)

    cwd = os.getcwd()

    # --- Phase 1: Allocate panes WITHOUT starting Claude ---
    print(f"🔧 Allocating {count} pane(s)...")
    panes = _allocate_panes(count, cwd=cwd)
    if not panes:
        print("❌ Failed to allocate panes", file=sys.stderr)
        sys.exit(1)

    branch = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        branch = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        pass

    # --- Phase 2: Write handoff BEFORE starting Claude ---
    for i, pane_ref in enumerate(panes):
        pane_num = pane_ref.replace("%", "")
        target = f"pane-{pane_num}"
        role = roles[i] if roles and i < len(roles) else (args.role or None)

        # Build injection markdown
        injection_md = _format_for_injection(handoff_md, source, role)

        # Write to Redis
        redis_ok = _write_to_redis(target, injection_md)

        # Write file fallback (always, as safety net)
        file_data = {
            "version": 1,
            "source_pane": source,
            "target_pane": target,
            "timestamp": time.time(),
            "cwd": cwd,
            "branch": branch,
            "role": role,
            "handoff_md": handoff_md,
        }
        _write_to_file(pane_num, file_data)

        channel = "Redis ✅" if redis_ok else "Redis ❌ (file fallback)"
        role_label = f" [{role}]" if role else ""
        print(f"  ✅ {target}{role_label} — {channel}")

    # --- Phase 3: Start Claude in allocated panes ---
    for pane_ref in panes:
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane_ref, "claude", "Enter"],
                timeout=5,
            )
        except Exception:
            pass

    print(f"\n🎯 {len(panes)} session(s) spawned. Use Ctrl-b + arrow key to switch.")


def cmd_write(args):
    """Write handoff without spawning (for manual pane setup)."""
    _require_tmux()
    target_pane = args.target
    if not target_pane:
        print("❌ --target is required (e.g. --target pane-42)", file=sys.stderr)
        sys.exit(1)

    # Validate target pane (path traversal prevention)
    pane_num = _validate_pane_num(target_pane)

    source = _pane_id()
    print(f"📋 Capturing context from {source}...")
    context = _capture_context(100)
    if not context:
        print("❌ Cannot capture tmux pane content", file=sys.stderr)
        sys.exit(1)

    print("🤖 Generating handoff summary...")
    handoff_md = _summarise_with_llm(context, role=args.role)
    injection_md = _format_for_injection(handoff_md, source, args.role)

    redis_ok = _write_to_redis(target_pane, injection_md)
    _write_to_file(
        pane_num,
        {
            "version": 1,
            "source_pane": source,
            "target_pane": target_pane,
            "timestamp": time.time(),
            "cwd": os.getcwd(),
            "role": args.role,
            "handoff_md": handoff_md,
        },
    )

    status = "Redis ✅" if redis_ok else "Redis ❌ (file only)"
    print(f"✅ Handoff written for {target_pane} — {status}")
    print("   Start `claude` in that pane to auto-load the handoff.")


def cmd_status(_args):
    """Show pending handoffs."""
    pending = _read_pending_handoffs()
    if not pending:
        print("  (no pending handoffs)")
        return

    print("Pending handoffs:")
    for d in pending:
        target = d.get("target_pane", "?")
        source = d.get("source_pane", "?")
        ts = d.get("timestamp", 0)
        age = int(time.time() - ts) if ts else 0
        if age < 60:
            age_str = f"{age}s ago"
        elif age < 3600:
            age_str = f"{age // 60}m ago"
        else:
            age_str = f"{age // 3600}h ago"

        goal = ""
        md = d.get("handoff_md", "")
        for line in md.split("\n"):
            if line.startswith("## Goal"):
                continue
            if line.strip() and not line.startswith("#"):
                goal = line.strip()[:50]
                break

        role = f" [{d.get('role')}]" if d.get("role") else ""
        print(f"  {target:>10}  from {source:<10}  {age_str:>8}  {goal}{role}")


def cmd_read(args):
    """Manually read a handoff."""
    pane_num = _validate_pane_num(args.pane)
    data = _read_from_file(pane_num)
    if data:
        print(data.get("handoff_md", "(empty)"))
    else:
        print(f"  (no handoff for pane {args.pane})")


def _read_from_file(pane_num: str) -> dict | None:
    if not _PANE_NUM_RE.match(pane_num):
        return None
    path = os.path.join(_HANDOFF_DIR, f"{pane_num}.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(
        prog="handoff",
        description="Context Relay — handoff session state to new Claude Code panes",
    )
    sub = p.add_subparsers(dest="cmd")

    sp_spawn = sub.add_parser("spawn", help="Summarise + spawn new CC session(s)")
    sp_spawn.add_argument("--count", type=int, default=1, help="Number of panes to spawn")
    sp_spawn.add_argument("--role", default=None, help="Role for the new session")
    sp_spawn.add_argument(
        "--roles", default=None, help="Comma-separated roles (parallel brainstorm)"
    )

    sp_write = sub.add_parser("write", help="Write handoff without spawning")
    sp_write.add_argument("--target", required=True, help="Target pane (e.g. pane-42)")
    sp_write.add_argument("--role", default=None, help="Role for the target session")

    sub.add_parser("status", help="Show pending handoffs")

    sp_read = sub.add_parser("read", help="Read a handoff for a pane")
    sp_read.add_argument("pane", help="Pane identifier (e.g. pane-42)")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)

    fn = {
        "spawn": cmd_spawn,
        "write": cmd_write,
        "status": cmd_status,
        "read": cmd_read,
    }
    fn[args.cmd](args)


if __name__ == "__main__":
    main()
