"""
Instinct distiller — SessionEnd + SessionStart handler.

SessionEnd: spawns a background worker that parses the session transcript
for friction signals (retries, corrections, fallbacks) and stages them
as instinct candidates in pending.jsonl.

SessionStart: reads pending.jsonl and notifies user of unreviewed instincts.

Architecture follows the claudemd_suggest.py pattern:
  extract → stage → notify → user review via /review-instincts
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC
from pathlib import Path

from .base import ALLOW, HookResult, message

STAGING_DIR = Path.home() / ".claude" / "data" / "instincts"
STAGING_FILE = STAGING_DIR / "pending.jsonl"
LOG_FILE = STAGING_DIR / "distill.log"
MAX_ENTRIES = 500
MAX_PREVIEW = 3


def handle(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    if event_type == "SessionEnd":
        return _handle_session_end(raw_input)
    if event_type == "SessionStart":
        return _handle_session_start()
    return ALLOW


# ---------------------------------------------------------------------------
# SessionEnd: spawn background distillation
# ---------------------------------------------------------------------------


def _handle_session_end(raw_input: str) -> HookResult:
    try:
        data = json.loads(raw_input) if raw_input else {}
        transcript_path = data.get("transcript_path")
        session_id = data.get("session_id", "")

        if not transcript_path or not Path(transcript_path).is_file():
            return ALLOW

        import subprocess

        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        log_fh = open(LOG_FILE, "a")
        subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                __file__,
                transcript_path,
                session_id,
            ],
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )
    except Exception:  # noqa: S110
        pass  # fail-open: never block Claude Code

    return ALLOW


# ---------------------------------------------------------------------------
# SessionStart: notify pending instincts
# ---------------------------------------------------------------------------


def _handle_session_start() -> HookResult:
    pending = _load_pending()
    if not pending:
        return ALLOW

    skill_groups: dict[str, int] = {}
    for entry in pending:
        skill = entry.get("skill_name", "unknown")
        skill_groups[skill] = skill_groups.get(skill, 0) + 1

    parts = [f"## Instinct 候選待審 ({len(pending)} 條, {len(skill_groups)} skills)"]
    for skill, count in sorted(skill_groups.items(), key=lambda x: -x[1])[:MAX_PREVIEW]:
        parts.append(f"- **{skill}**: {count} friction signal(s)")

    if len(skill_groups) > MAX_PREVIEW:
        parts.append(f"  ... 還有 {len(skill_groups) - MAX_PREVIEW} skills")

    parts.append("使用 `/review-instincts` 審閱")

    return message("\n".join(parts))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pending() -> list[dict]:
    if not STAGING_FILE.is_file():
        return []
    try:
        entries = []
        for line in STAGING_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not entry.get("reviewed", False):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
        return entries
    except Exception:
        return []


# ===================================================================
# Background worker — invoked as __main__
# ===================================================================

# Friction signal patterns (conservative heuristics, no LLM needed)
_FRICTION_PATTERNS = [
    (re.compile(r"(?:retrying|retry|let me try again)", re.I), "retry"),
    (re.compile(r"(?:that (?:didn.t|did not) work|failed|error)", re.I), "failure"),
    (re.compile(r"(?:不[，,]|不對|錯了|不是這樣|重來)", re.I), "correction"),  # noqa: RUF001
    (re.compile(r"(?:fallback|workaround|alternative approach)", re.I), "fallback"),
    (re.compile(r"(?:no not that|don.t do that|stop|別這樣做)", re.I), "correction"),
]


def _extract_friction_signals(transcript_path: str) -> list[dict]:
    """Parse transcript JSONL for friction signals."""
    signals: list[dict] = []
    path = Path(transcript_path)
    if not path.is_file():
        return signals

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Look at user messages and assistant tool failures
            msg_type = entry.get("type", "")
            content = ""

            if msg_type == "human":
                content = _extract_text(entry)
            elif msg_type == "assistant":
                # Check for tool use errors in content blocks
                for block in entry.get("content", []):
                    if block.get("type") == "tool_result" and block.get("is_error"):
                        content += block.get("content", "") + " "

            if not content:
                continue

            for pattern, signal_type in _FRICTION_PATTERNS:
                if pattern.search(content):
                    # Try to identify which skill is involved
                    skill_name = _guess_skill(entry, content)
                    signals.append(
                        {
                            "signal_type": signal_type,
                            "skill_name": skill_name,
                            "summary": content[:200].strip(),
                            "line_hint": entry.get("index", 0),
                        }
                    )
    except Exception:  # noqa: S110
        pass  # fail-open: transcript may be malformed

    return signals


def _extract_text(entry: dict) -> str:
    """Extract plain text from a transcript entry."""
    content = entry.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""


def _guess_skill(entry: dict, content: str) -> str:
    """Best-effort guess at which skill is relevant."""
    # Look for /skill-name patterns
    match = re.search(r"/([a-z][a-z0-9-]+)", content)
    if match:
        return match.group(1)
    # Look for Skill tool usage in surrounding context
    for block in entry.get("content", []) if isinstance(entry.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            if block.get("name") == "Skill":
                return block.get("input", {}).get("skill", "unknown")
    return "general"


def _summary_hash(skill_name: str, signal_type: str, summary: str) -> str:
    """Deterministic hash for dedup."""
    key = f"{skill_name}:{signal_type}:{summary[:80]}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _dedup_and_append(signals: list[dict], session_id: str) -> None:
    """Dedup against existing entries and append new ones."""
    existing: dict[str, dict] = {}
    if STAGING_FILE.is_file():
        for line in STAGING_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                h = entry.get("hash", "")
                if h:
                    existing[h] = entry
            except json.JSONDecodeError:
                continue

    new_entries: list[dict] = []
    from datetime import datetime

    now = datetime.now(UTC).isoformat()

    for sig in signals:
        h = _summary_hash(sig["skill_name"], sig["signal_type"], sig["summary"])
        if h in existing:
            # Increment occurrences
            existing[h]["occurrences"] = existing[h].get("occurrences", 1) + 1
            existing[h]["last_seen"] = now
        else:
            entry = {
                "hash": h,
                "skill_name": sig["skill_name"],
                "signal_type": sig["signal_type"],
                "summary": sig["summary"],
                "evidence": [f"session:{session_id}"],
                "occurrences": 1,
                "reviewed": False,
                "ts": now,
                "last_seen": now,
            }
            existing[h] = entry
            new_entries.append(entry)

    # Rewrite file (prune old reviewed entries, cap at MAX_ENTRIES)
    all_entries = sorted(existing.values(), key=lambda x: x.get("last_seen", ""), reverse=True)
    # Keep unreviewed first, then recent reviewed
    unreviewed = [e for e in all_entries if not e.get("reviewed", False)]
    reviewed = [e for e in all_entries if e.get("reviewed", False)]
    final = (unreviewed + reviewed)[:MAX_ENTRIES]

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    with open(STAGING_FILE, "w", encoding="utf-8") as f:
        for entry in final:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _main(transcript_path: str, session_id: str) -> None:
    """Background worker entry point."""
    signals = _extract_friction_signals(transcript_path)
    if not signals:
        return

    # Group by skill
    skill_signals: dict[str, list[dict]] = {}
    for sig in signals:
        skill_signals.setdefault(sig["skill_name"], []).append(sig)

    # Flatten for dedup
    _dedup_and_append(signals, session_id)

    print(f"[instinct_distiller] Processed {len(signals)} signals from {len(skill_signals)} skills")


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) >= 3:
        _main(_sys.argv[1], _sys.argv[2])
    elif len(_sys.argv) >= 2:
        _main(_sys.argv[1], "unknown")
