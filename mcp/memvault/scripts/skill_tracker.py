#!/usr/bin/env python3
"""skill_tracker.py — PostToolUse hook for Skill invocations.
Triggered by Claude Code PostToolUse (matcher: "Skill").
POSTs to Core API (localhost:8801), falls back to JSONL.

stdin: Hook JSON payload from Claude Code
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CORE_API_URL = "http://localhost:8801"
SPACE_ID = "default"
FALLBACK_FILE = Path.home() / "Claude" / "memvault" / "skill-invocations.jsonl"
LOG_FILE = Path.home() / "Claude" / "memvault" / "logs" / "skill-tracker.log"

# Extend PATH to match shell script behavior
extra_paths = [
    "/opt/homebrew/bin",
    str(Path.home() / ".local" / "bin"),
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
]
current_path = os.environ.get("PATH", "")
os.environ["PATH"] = ":".join(extra_paths + [current_path])


def _log(msg: str) -> None:
    """Write timestamped log message to log file."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[skill-tracker] {ts} {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_post(url: str, data: bytes, timeout: int = 5) -> tuple:
    """POST request, return (status_code, response_body). Returns ('000', '') on error."""
    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return str(e.code), body
    except Exception:
        return "000", ""


def main() -> None:
    # Always exit 0 — safety net
    try:
        _main()
    except Exception:
        pass
    sys.exit(0)


def _main() -> None:
    # ── Read stdin ─────────────────────────────────────────────────────────────
    try:
        raw = sys.stdin.read()
        input_data = json.loads(raw)
    except Exception:
        return

    # ── Filter: only process Skill tool calls ──────────────────────────────────
    tool_name = input_data.get("tool_name", "")
    if "Skill" not in tool_name:
        sys.exit(0)

    # ── Extract fields ─────────────────────────────────────────────────────────
    tool_input = input_data.get("tool_input", {})

    # Try multiple possible field names for skill_name
    skill_name = (
        tool_input.get("skill_name")
        or tool_input.get("name")
        or _first_string_value(tool_input)
        or "unknown"
    )

    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "")
    invoked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Detect outcome from tool_response
    try:
        raw_response = json.dumps(input_data.get("tool_response", ""))
    except Exception:
        raw_response = ""
    raw_response_lower = raw_response.lower()

    outcome = (
        "failure"
        if ("error" in raw_response_lower or "failed" in raw_response_lower)
        else "success"
    )

    _log(f"skill='{skill_name}' session='{session_id}' outcome='{outcome}'")

    # ── Build POST body ────────────────────────────────────────────────────────
    post_body_dict = {
        "skill_name": skill_name,
        "source_session": session_id,
        "cwd": cwd,
        "invoked_at": invoked_at,
        "outcome": outcome,
        "duration_ms": None,
    }

    try:
        post_body = json.dumps(post_body_dict).encode("utf-8")
    except Exception:
        _log("ERROR: failed to build POST body, aborting")
        return

    # ── Primary path: POST to Core API ────────────────────────────────────────
    http_status, _ = http_post(
        f"{CORE_API_URL}/api/memvault/kg/skills/invoke?space_id={SPACE_ID}",
        post_body,
        timeout=5,
    )

    if http_status == "201":
        _log(f"API OK (201) skill='{skill_name}'")

        # ── Knowledge Flywheel: capture skill output as memory block ─────────
        knowledge_skills = {
            "smart-search",
            "company-intel",
            "competitive-intel",
            "content-writer",
            "brainstorming",
            "meeting-insights",
        }
        if skill_name in knowledge_skills:
            clean_response = raw_response[:2000]
            resp_len = len(clean_response)

            if resp_len > 200:
                topic_preview = clean_response[:80].replace("\n", " ")
                block_body_dict = {
                    "topic": f"skill:{skill_name} — {topic_preview}",
                    "content": clean_response,
                    "block_type": "skill_knowledge",
                    "tags": [f"skill:{skill_name}", "auto-captured", "knowledge-flywheel"],
                    "source": "skill-tracker",
                }
                try:
                    block_body = json.dumps(block_body_dict).encode("utf-8")
                    block_status, _ = http_post(
                        f"{CORE_API_URL}/api/memvault/blocks?space_id={SPACE_ID}",
                        block_body,
                        timeout=5,
                    )
                    if block_status == "201":
                        _log(f"Knowledge captured for skill='{skill_name}' ({resp_len} chars)")
                    else:
                        _log(
                            f"Knowledge capture failed (HTTP {block_status}) "
                            f"for skill='{skill_name}'"
                        )
                except Exception as e:
                    _log(f"Knowledge capture error: {e}")
            else:
                _log(f"Skipping knowledge capture — response too short ({resp_len} chars)")
        # ── End Knowledge Flywheel ────────────────────────────────────────────

        return

    _log(f"API FAIL (status={http_status}), writing to fallback JSONL")

    # ── Fallback: JSONL ────────────────────────────────────────────────────────
    fallback_record_dict = {
        "skill_name": skill_name,
        "source_session": session_id,
        "cwd": cwd,
        "invoked_at": invoked_at,
        "outcome": outcome,
        "duration_ms": None,
        "ingested": False,
    }

    try:
        fallback_record = json.dumps(fallback_record_dict)
        FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FALLBACK_FILE, "a", encoding="utf-8") as f:
            f.write(fallback_record + "\n")
        _log(f"JSONL written skill='{skill_name}'")
    except Exception as e:
        _log(f"ERROR: failed to build/write fallback record: {e}")


def _first_string_value(d: dict) -> "str | None":
    """Return first string value from dict entries, or None."""
    for v in d.values():
        if isinstance(v, str):
            return v
    return None


if __name__ == "__main__":
    main()
