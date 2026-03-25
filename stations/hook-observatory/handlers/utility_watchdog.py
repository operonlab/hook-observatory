"""Utility Watchdog — Memento-Skills self-evolution trigger.

SessionEnd: spawn background check for low-utility skills used in session.
SessionStart: inject context reminder if flagged proposals exist.

Design:
  - Fail-open: all external calls in try/except, never block Claude Code.
  - Background: SessionEnd spawns detached process (same pattern as session_pipeline).
  - Dynamic threshold: delta = base + factor * log(n_total).
  - Proposals stored in JSONL (lightweight, short-lived).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .base import ALLOW, HookResult, message

log = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".claude" / "data" / "utility-watchdog"
_PROPOSALS_FILE = _DATA_DIR / "proposals.jsonl"
_CREATE_PROPOSALS_FILE = _DATA_DIR / "create-proposals.jsonl"
_CHECK_SCRIPT = str(
    Path.home() / "workshop" / "stations" / "anvil" / "scripts" / "utility_check.py"
)


def handle(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    """Route to SessionEnd or SessionStart handler."""
    if event_type == "SessionEnd":
        return _handle_session_end(raw_input)
    if event_type == "SessionStart":
        return _handle_session_start(raw_input)
    return ALLOW


# ---------------------------------------------------------------------------
# SessionEnd: spawn background utility check
# ---------------------------------------------------------------------------


def _handle_session_end(raw_input: str) -> HookResult:
    try:
        data = json.loads(raw_input) if raw_input else {}
        session_id = data.get("session_id", "")
        if not session_id:
            return ALLOW

        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Spawn detached background process to check utility
        python = os.path.expanduser("~/.local/bin/python3")
        log_file = open(_DATA_DIR / "watchdog.log", "a")
        subprocess.Popen(
            [python, _CHECK_SCRIPT, session_id],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    except Exception:
        pass  # fail-open

    return ALLOW


# ---------------------------------------------------------------------------
# SessionStart: inject reminder if flagged proposals exist
# ---------------------------------------------------------------------------

_PROPOSAL_THRESHOLD = 3  # need N+ proposals for same skill before alerting


def _handle_session_start(raw_input: str) -> HookResult:
    try:
        if not _PROPOSALS_FILE.exists():
            return ALLOW

        # Count proposals per skill
        skill_counts: dict[str, list[dict]] = {}
        lines = _PROPOSALS_FILE.read_text().strip().split("\n")
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                name = entry.get("skill_name", "")
                if name:
                    skill_counts.setdefault(name, []).append(entry)
            except json.JSONDecodeError:
                continue

        # Filter skills with enough proposals
        flagged = {}
        for name, entries in skill_counts.items():
            if len(entries) >= _PROPOSAL_THRESHOLD:
                # Use most recent utility score
                latest = entries[-1]
                flagged[name] = latest.get("utility", "?")

        if not flagged:
            return ALLOW

        # Build reminder message
        parts = [f"{name}({score})" for name, score in flagged.items()]
        msg = (
            f"[Utility Watchdog] {len(flagged)} skills below threshold: "
            f"{', '.join(parts)}. Consider /skill-optimizer."
        )
        return message(msg)

    except Exception:
        pass  # fail-open

    return ALLOW
