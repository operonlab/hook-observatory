#!/Users/joneshong/.local/bin/python3
"""Background utility check — spawned by utility_watchdog on SessionEnd.

For each skill used in the session, checks if utility is below dynamic
threshold. If so, appends a proposal to the JSONL file.

Usage: python utility_check.py <session_id>

Dynamic threshold: delta = base + factor * ln(n_total)
  - base=0.7, factor=0.02
  - Higher usage → higher bar (more popular skills held to stricter standard)
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Add workshop SDK to path
sys.path.insert(0, str(Path.home() / "workshop" / "libs" / "python" / "src"))

if TYPE_CHECKING:
    from sdk_client.anvil import AnvilClient

PROPOSALS_FILE = Path.home() / ".claude" / "data" / "utility-watchdog" / "proposals.jsonl"
CREATE_PROPOSALS_FILE = (
    Path.home() / ".claude" / "data" / "utility-watchdog" / "create-proposals.jsonl"
)
THRESHOLD_BASE = 0.7
THRESHOLD_FACTOR = 0.02
MIN_INVOCATIONS = 5


def _has_failures(client, skill_name: str, session_id: str) -> bool:
    """Check if a skill has any failures in this session."""
    try:
        data = client.list_invocations(skill_name=skill_name, session_id=session_id, limit=500)
        for inv in data.get("items", []):
            if not inv.get("success", True):
                return True
    except Exception:
        pass
    return False


def _check_create_on_miss(client: "AnvilClient", session_id: str, tool_count: int) -> None:
    """Detect sessions with no skill usage but real work done."""
    try:
        if tool_count < 3:
            return
        CREATE_PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "session_id": session_id,
            "tool_count": tool_count,
            "ts": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        }
        with open(CREATE_PROPOSALS_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"[utility_check] CreateOnMiss for session {session_id[:8]}", file=sys.stderr)
    except Exception:
        pass  # best-effort


def dynamic_threshold(n_total: int) -> float:
    """Compute dynamic utility threshold: base + factor * ln(n_total)."""
    if n_total <= 1:
        return THRESHOLD_BASE
    return THRESHOLD_BASE + THRESHOLD_FACTOR * math.log(n_total)


def main(session_id: str) -> None:
    from sdk_client.anvil import AnvilClient

    client = AnvilClient(base_url="http://127.0.0.1:4103")

    # 1. Get skills used in this session (use session_id filter!)
    try:
        invocations = client.list_invocations(session_id=session_id, limit=500)
    except Exception as e:
        print(f"[utility_check] Cannot reach Anvil: {e}", file=sys.stderr)
        return

    items = invocations.get("items", [])
    session_skills = {i.get("skill_name", "") for i in items if i.get("category") == "skill"}
    session_skills.discard("")

    # CreateOnMiss: check BEFORE early return (C2 fix)
    if not session_skills:
        _check_create_on_miss(client, session_id, len(items))
        return

    # 2. Check utility for each skill
    proposals = []
    for skill_name in session_skills:
        try:
            data = client.get_utility(skill_name)
        except Exception:
            continue

        n_total = data.get("total_invocations", 0)
        utility = data.get("utility_score")

        if n_total < MIN_INVOCATIONS:
            continue
        if utility is None:
            continue

        threshold = dynamic_threshold(n_total)
        if utility < threshold:
            proposals.append(
                {
                    "skill_name": skill_name,
                    "utility": round(utility, 4),
                    "threshold": round(threshold, 4),
                    "n_total": n_total,
                    "session_id": session_id,
                    "ts": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                }
            )

    # 2b. Trigger attribution for sessions with multi-skill failures
    failed_skills = [s for s in session_skills if _has_failures(client, s, session_id)]
    if len(failed_skills) >= 2:
        try:
            client._post(f"/api/anvil/invocations/attribute/{session_id}")
        except Exception:
            pass  # best-effort

    # 3. Append proposals
    if proposals:
        PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSALS_FILE, "a") as f:
            for p in proposals:
                f.write(json.dumps(p) + "\n")
        print(
            f"[utility_check] {len(proposals)} proposals for session {session_id[:8]}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: utility_check.py <session_id>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
