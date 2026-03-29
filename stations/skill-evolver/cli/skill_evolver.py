#!/usr/bin/env python3
"""Skill Evolution Engine CLI — manual trigger + report viewer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from skill_evolver.config import LEDGER_PATH, REPORTS_DIR, Config
from skill_evolver.reporter import save_report
from skill_evolver.runner import EvolutionResult, evolve_skill
from skill_evolver.selector import select_skills


def cmd_run(args: argparse.Namespace) -> int:
    """Run evolution loop (manual trigger or Cronicle)."""
    config = Config.load(
        Path(args.config) if args.config else None
    )

    if args.max_skills:
        config.max_skills_per_night = args.max_skills
    if args.max_rounds:
        config.max_rounds_per_skill = args.max_rounds

    # Select skills
    targets = select_skills(config)
    if not targets:
        print("No eligible skills found (check golden_cases/ and evolution.md)")
        return 1

    print(f"Selected {len(targets)} skills for evolution:")
    for t in targets:
        print(f"  - {t.name} ({t.priority}, {t.invocations_7d} invocations/7d)")
    print()

    # Shared eval budget
    eval_budget = [config.max_eval_calls]
    results: list[EvolutionResult] = []

    for t in targets:
        print(f"--- Evolving: {t.name} (budget remaining: {eval_budget[0]}) ---")
        result = evolve_skill(t, config, eval_budget)
        results.append(result)

        if result.improvement > 0:
            print(f"  ✓ Improved by {result.improvement:.1f}% "
                  f"({result.rounds_kept}/{result.rounds_run} kept)")
        else:
            print(f"  · No improvement ({result.rounds_run} rounds)")

        if eval_budget[0] <= 0:
            print("\nEval budget exhausted — stopping.")
            break

    # Generate report
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    report_path = save_report(results, date_str)
    print(f"\nReport saved: {report_path}")

    # Summary
    improved = [r for r in results if r.improvement > 0]
    print(f"\nSummary: {len(improved)}/{len(results)} skills improved")

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show evolution status and recent results."""
    # Latest report
    if REPORTS_DIR.exists():
        reports = sorted(REPORTS_DIR.glob("evolution-*.md"), reverse=True)
        if reports:
            latest = reports[0]
            print(f"Latest report: {latest.name}")
            print(latest.read_text()[:2000])
            return 0

    print("No evolution reports found yet.")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    """Show evolution ledger (cross-night learning data)."""
    if not LEDGER_PATH.exists():
        print("No ledger data yet.")
        return 0

    ledger = json.loads(LEDGER_PATH.read_text())
    recent = ledger[-(args.last):]

    if args.json:
        print(json.dumps(recent, indent=2, ensure_ascii=False))
        return 0

    print(f"Ledger: {len(ledger)} total entries (showing last {len(recent)})")
    print()
    print(f"{'Timestamp':<20} {'Skill':<20} {'R':<3} {'Theme':<12} {'Verdict':<8} {'Δ':>6}")
    print("-" * 75)
    for entry in recent:
        ts = entry["timestamp"][:19]
        print(
            f"{ts:<20} {entry['skill']:<20} {entry['round']:<3} "
            f"{entry['theme']:<12} {entry['verdict']:<8} {entry['delta']:>+6.2f}"
        )

    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Show what would be evolved without running."""
    config = Config.load(
        Path(args.config) if args.config else None
    )
    targets = select_skills(config)

    if not targets:
        print("No eligible skills found.")
        return 0

    print(f"Would evolve {len(targets)} skills:")
    for t in targets:
        print(f"  - {t.name}")
        print(f"    Priority: {t.priority}")
        print(f"    Invocations (7d): {t.invocations_7d}")
        print(f"    Success rate: {t.success_rate:.0%}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="skill-evolver",
        description="Skill Evolution Engine — AutoResearch-inspired overnight skill optimization",
    )
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run evolution loop")
    p_run.add_argument("--config", help="Config JSON path")
    p_run.add_argument("--max-skills", type=int, help="Override max skills per run")
    p_run.add_argument("--max-rounds", type=int, help="Override max rounds per skill")
    p_run.add_argument("--json", action="store_true", help="Output JSON results")

    # status
    sub.add_parser("status", help="Show latest report")

    # ledger
    p_ledger = sub.add_parser("ledger", help="Show evolution ledger")
    p_ledger.add_argument("--last", type=int, default=20, help="Show last N entries")
    p_ledger.add_argument("--json", action="store_true", help="Output JSON")

    # dry-run
    p_dry = sub.add_parser("dry-run", help="Preview what would be evolved")
    p_dry.add_argument("--config", help="Config JSON path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "run": cmd_run,
        "status": cmd_status,
        "ledger": cmd_ledger,
        "dry-run": cmd_dry_run,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
