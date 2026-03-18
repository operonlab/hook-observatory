#!/usr/bin/env python3
"""synthesis_runner.py — Memvault KG Synthesis Orchestrator

Runs the full daily synthesis pipeline:
  1. Community Detection (Leiden) — builds graph communities at 3 resolution levels
  2. Community Summary (DeepSeek V3) — generates LLM summaries for each level

Usage:
    ~/.local/bin/python3 mcp/memvault/pipelines/synthesis_runner.py
    ~/.local/bin/python3 mcp/memvault/pipelines/synthesis_runner.py --dry-run
    ~/.local/bin/python3 mcp/memvault/pipelines/synthesis_runner.py --skip-summaries

Environment:
    CORE_API_URL      — defaults to http://localhost:8801
    MEMVAULT_SPACE_ID — defaults to default
    DEEPSEEK_API_KEY  — required for summary generation (unless --skip-summaries)
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

PYTHON = os.path.expanduser("~/.local/bin/python3")
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_LEVELS = [1, 0, 2]  # medium first (most useful), then fine, then coarse


def run_pipeline(name: str, cmd: list[str], env: dict) -> tuple[bool, float]:
    """Run a pipeline subprocess and return (success, duration_seconds)."""
    print(f"\n{'─' * 60}")
    print(f"  Running: {name}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'─' * 60}\n")

    t0 = time.monotonic()
    result = subprocess.run(cmd, env=env)
    elapsed = time.monotonic() - t0

    ok = result.returncode == 0
    status = "OK" if ok else f"FAILED (exit {result.returncode})"
    print(f"\n  [{name}] {status} — {elapsed:.1f}s")
    return ok, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Memvault KG synthesis orchestrator")
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to all pipelines")
    parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Only run community detection, skip LLM summaries",
    )
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=SUMMARY_LEVELS,
        choices=[0, 1, 2],
        help="Summary levels to generate (default: 1 0 2)",
    )
    args = parser.parse_args()

    env = {**os.environ, "MEMVAULT_SPACE_ID": args.space_id}

    print("=" * 60)
    print("  Memvault — KG Synthesis Runner")
    print("=" * 60)
    print(f"  Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Space ID : {args.space_id}")
    print(f"  Dry run  : {args.dry_run}")
    print(f"  Summaries: {'skip' if args.skip_summaries else f'levels {args.levels}'}")
    print("=" * 60)

    results: list[tuple[str, bool, float]] = []

    # Step 1: Community Detection (Leiden)
    community_cmd = [
        PYTHON,
        os.path.join(PIPELINE_DIR, "community_pipeline.py"),
        "--space-id",
        args.space_id,
    ]
    if args.dry_run:
        community_cmd.append("--dry-run")

    ok, elapsed = run_pipeline("Community Detection (Leiden)", community_cmd, env)
    results.append(("community_detection", ok, elapsed))

    if not ok:
        print("\n[ABORT] Community detection failed — skipping summaries.")
        _print_summary(results)
        sys.exit(1)

    # Step 2: Community Summaries (one per resolution level)
    if not args.skip_summaries:
        for level in args.levels:
            level_name = {0: "fine", 1: "medium", 2: "coarse"}[level]
            summary_cmd = [
                PYTHON,
                os.path.join(PIPELINE_DIR, "community_summary_pipeline.py"),
                "--space-id",
                args.space_id,
                "--level",
                str(level),
            ]
            if args.dry_run:
                summary_cmd.append("--dry-run")

            ok, elapsed = run_pipeline(
                f"Community Summary L{level} ({level_name})", summary_cmd, env
            )
            results.append((f"summary_L{level}", ok, elapsed))

            if not ok:
                print(f"\n[warn] Summary L{level} failed — continuing with remaining levels.")

    _print_summary(results)

    failed = sum(1 for _, ok, _ in results if not ok)
    if failed:
        sys.exit(1)


def _print_summary(results: list[tuple[str, bool, float]]) -> None:
    total_time = sum(t for _, _, t in results)
    print(f"\n{'=' * 60}")
    print("  Synthesis Runner — Summary")
    print(f"{'=' * 60}")
    for name, ok, elapsed in results:
        status = "OK" if ok else "FAIL"
        print(f"  [{status:4s}] {name:<35s} {elapsed:6.1f}s")
    print(f"{'─' * 60}")
    print(f"  Total: {total_time:.1f}s | Failed: {sum(1 for _, ok, _ in results if not ok)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
