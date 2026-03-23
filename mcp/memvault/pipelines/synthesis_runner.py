#!/usr/bin/env python3
"""synthesis_runner.py — Memvault KG Synthesis Orchestrator

Runs the full daily synthesis pipeline:
  1. Community Detection (Leiden) — builds graph communities at 3 resolution levels
  2. Community Summary (DeepSeek V3) — generates LLM summaries for each level
  3. Interest Snapshot — aggregates query_journal into attention profiles
  4. User Insights — LLM-generated natural language insights from interest data

Usage:
    python3 mcp/memvault/pipelines/synthesis_runner.py
    python3 mcp/memvault/pipelines/synthesis_runner.py --dry-run
    python3 mcp/memvault/pipelines/synthesis_runner.py --skip-summaries
    python3 mcp/memvault/pipelines/synthesis_runner.py --skip-insights

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

UV = "/opt/homebrew/bin/uv"
WORKSHOP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CORE_PROJECT = os.path.join(WORKSHOP_ROOT, "core")
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_LEVELS = [1, 0, 2]  # medium first (most useful), then fine, then coarse


PIPELINE_TIMEOUT = 900  # 15 minutes max per pipeline step


def run_pipeline(
    name: str, cmd: list[str], env: dict, *, timeout: int = PIPELINE_TIMEOUT
) -> tuple[bool, float]:
    """Run a pipeline subprocess and return (success, duration_seconds).

    Uses process group kill to ensure all child processes (including grandchildren
    spawned by 'uv run') are terminated on timeout.
    """
    print(f"\n{'─' * 60}")
    print(f"  Running: {name}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'─' * 60}\n")

    import signal

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        proc.wait(timeout=timeout)
        elapsed = time.monotonic() - t0
        ok = proc.returncode == 0
        status = "OK" if ok else f"FAILED (exit {proc.returncode})"
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        # Kill entire process group (uv → python grandchild)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
        ok = False
        status = f"TIMEOUT after {elapsed:.0f}s"

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
    parser.add_argument(
        "--skip-insights",
        action="store_true",
        help="Skip interest snapshot and user insight generation",
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

    # Step 1: Community Detection (Leiden) — needs igraph from core venv
    community_cmd = [
        UV,
        "run",
        "--project",
        CORE_PROJECT,
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
                UV,
                "run",
                "--project",
                CORE_PROJECT,
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

    # Step 3: Interest Snapshot — aggregates query_journal into attention profiles
    if not args.skip_insights:
        import json
        import urllib.request

        core_api = os.environ.get("CORE_API_URL", "http://localhost:8801")
        t0 = time.monotonic()
        try:
            url = f"{core_api}/api/memvault/kg/interest/generate?space_id={args.space_id}"
            req = urllib.request.Request(url, method="POST")  # noqa: S310
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                data = json.loads(resp.read())
            elapsed = time.monotonic() - t0
            ok = True
            print(f"\n  [Interest Snapshot] OK — {elapsed:.1f}s")
            print(f"    {json.dumps(data, ensure_ascii=False)}")
        except Exception as e:
            elapsed = time.monotonic() - t0
            ok = False
            print(f"\n  [Interest Snapshot] FAILED — {elapsed:.1f}s: {e}", file=sys.stderr)
        results.append(("interest_snapshot", ok, elapsed))

    # Step 4: User Insights — LLM-generated insights from interest data
    if not args.skip_insights:
        insight_cmd = [
            UV,
            "run",
            "--project",
            CORE_PROJECT,
            os.path.join(PIPELINE_DIR, "user_insight_pipeline.py"),
            "--space-id",
            args.space_id,
        ]
        if args.dry_run:
            insight_cmd.append("--dry-run")

        ok, elapsed = run_pipeline("User Insights (Haiku)", insight_cmd, env)
        results.append(("user_insights", ok, elapsed))

        if not ok:
            print("\n[warn] User insights failed — non-critical, continuing.")

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
