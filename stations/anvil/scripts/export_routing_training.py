#!/Users/joneshong/.local/bin/python3
"""Export training data for behaviour-aligned skill routing.

Joins intents (user requests) with invocations (skill executions) to create
(query, skill, success) triples for contrastive learning (InfoNCE).

Output: JSONL with {anchor, positive, negative} format for fine-tuning
Qwen3-Embedding-0.6B via MLX.

Usage:
    python export_routing_training.py [--output FILE] [--min-pairs N]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Add workshop SDK to path
sys.path.insert(0, str(Path.home() / "workshop" / "libs" / "python" / "src"))

DEFAULT_OUTPUT = str(Path.home() / ".claude" / "data" / "skill-router" / "training.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export skill routing training data")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help="Output JSONL path")
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=100,
        help="Minimum pairs required to export",
    )
    parser.add_argument("--window-days", type=int, default=90, help="Time window")
    args = parser.parse_args()

    from workshop.clients.anvil import AnvilClient

    client = AnvilClient()

    # 1. Get all intents (user requests)
    print("[export] Fetching intents...", file=sys.stderr)
    try:
        # Use invocations API with session filtering
        all_invocations = []
        offset = 0
        while True:
            batch = client.list_invocations(limit=500, offset=offset)
            items = batch.get("items", [])
            if not items:
                break
            all_invocations.extend(items)
            offset += len(items)
            if offset >= batch.get("total", 0):
                break
    except Exception as e:
        print(f"[export] Error fetching invocations: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[export] Total invocations: {len(all_invocations)}", file=sys.stderr)

    # 2. Group by session → build (intent_context, skill, success) triples
    sessions: dict[str, list[dict]] = {}
    for inv in all_invocations:
        sid = inv.get("session_id")
        if sid and inv.get("category") == "skill":
            sessions.setdefault(sid, []).append(inv)

    # 3. Build training pairs
    # Positive: skill was invoked AND succeeded
    # Hard negative: skill was invoked BUT failed (same domain, wrong execution)
    # In-batch negative: random other skill (different domain)
    all_skills = list(
        {inv["skill_name"] for inv in all_invocations if inv.get("category") == "skill"}
    )

    pairs = []
    for sid, invocations in sessions.items():
        for inv in invocations:
            skill = inv["skill_name"]
            success = inv.get("success", True)
            # Use skill_name + payload args as the "query" proxy
            payload = inv.get("payload") or {}
            query = payload.get("args", "") or skill

            if success:
                # Pick a random negative skill (different from current)
                negatives = [s for s in all_skills if s != skill]
                if negatives:
                    neg = random.choice(negatives)  # noqa: S311
                    pairs.append(
                        {
                            "anchor": query,
                            "positive": skill,
                            "negative": neg,
                            "session_id": sid,
                        }
                    )
            else:
                # Failed invocation → the skill itself is a hard negative
                # and any successful skill from the same session is positive
                successful = [
                    i["skill_name"]
                    for i in invocations
                    if i.get("success", True) and i["skill_name"] != skill
                ]
                if successful:
                    pos = successful[0]
                    pairs.append(
                        {
                            "anchor": query,
                            "positive": pos,
                            "negative": skill,  # hard negative
                            "session_id": sid,
                        }
                    )

    print(f"[export] Training pairs: {len(pairs)}", file=sys.stderr)

    if len(pairs) < args.min_pairs:
        print(
            f"[export] Insufficient pairs ({len(pairs)} < {args.min_pairs}). "
            "Need more invocation data. Skipping export.",
            file=sys.stderr,
        )
        sys.exit(0)

    # 4. Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    random.shuffle(pairs)
    with open(output_path, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    print(f"[export] Wrote {len(pairs)} pairs to {output_path}", file=sys.stderr)

    # 5. Summary stats
    skill_counts: dict[str, int] = {}
    for p in pairs:
        skill_counts[p["positive"]] = skill_counts.get(p["positive"], 0) + 1
    print("\n[export] Top skills in training data:", file=sys.stderr)
    for skill, count in sorted(skill_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {skill:<30} {count} pairs", file=sys.stderr)


if __name__ == "__main__":
    main()
