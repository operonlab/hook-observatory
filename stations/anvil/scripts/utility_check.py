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

# Add workshop SDK to path
sys.path.insert(0, str(Path.home() / "workshop" / "libs" / "python" / "src"))

PROPOSALS_FILE = Path.home() / ".claude" / "data" / "utility-watchdog" / "proposals.jsonl"
THRESHOLD_BASE = 0.7
THRESHOLD_FACTOR = 0.02
MIN_INVOCATIONS = 5


def dynamic_threshold(n_total: int) -> float:
    """Compute dynamic utility threshold: base + factor * ln(n_total)."""
    if n_total <= 1:
        return THRESHOLD_BASE
    return THRESHOLD_BASE + THRESHOLD_FACTOR * math.log(n_total)


def main(session_id: str) -> None:
    from workshop.clients.anvil import AnvilClient

    client = AnvilClient()

    # 1. Get skills used in this session
    try:
        invocations = client.list_invocations(limit=100)
    except Exception as e:
        print(f"[utility_check] Cannot reach Anvil: {e}", file=sys.stderr)
        return

    # Filter to this session's skill invocations
    items = invocations.get("items", [])
    session_skills = set()
    for inv in items:
        if inv.get("session_id") == session_id and inv.get("category") == "skill":
            session_skills.add(inv.get("skill_name", ""))

    session_skills.discard("")
    if not session_skills:
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
