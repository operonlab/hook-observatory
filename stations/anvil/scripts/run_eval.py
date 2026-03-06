#!/Users/joneshong/.local/bin/python3
"""
Skill evaluation executor -- spawns claude -p subprocesses.

Runs eval cases defined in a skill's evals.json file by spawning headless
Claude Code processes. Collects transcripts, timing, and exit status for
downstream grading by the Grader agent.

Usage:
    python3 run_eval.py --skill finance
    python3 run_eval.py --skill finance --evals-path ~/.claude/skills/finance/evals.json
    python3 run_eval.py --skill finance --workers 3 --timeout 120
    python3 run_eval.py --skill finance --output /tmp/eval-results.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def run_single_eval(eval_case: dict, skill_name: str, timeout: int = 120) -> dict:
    """Run a single eval case via claude -p subprocess.

    Args:
        eval_case: Dict with keys: id, prompt, expected_output, expectations, tags.
        skill_name: Name of the skill being evaluated.
        timeout: Maximum seconds to wait for the subprocess.

    Returns:
        Dict with eval results including transcript, timing, and status.
    """
    prompt = eval_case.get("prompt", "")
    eval_id = eval_case.get("id", 0)

    # Remove CLAUDECODE env var to allow nested calls.
    # When running inside Claude Code, this env var prevents nested invocations.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    start = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        duration = time.time() - start

        # Parse output -- claude -p with --output-format json returns structured data
        output = result.stdout.strip()
        try:
            parsed = json.loads(output)
            transcript = parsed.get("result", output)
        except json.JSONDecodeError:
            transcript = output

        return {
            "eval_id": eval_id,
            "skill_name": skill_name,
            "prompt": prompt,
            "transcript": transcript,
            "stderr": result.stderr[:500] if result.stderr else "",
            "exit_code": result.returncode,
            "duration_s": round(duration, 2),
            "success": result.returncode == 0,
            "expectations": eval_case.get("expectations", []),
            "expected_output": eval_case.get("expected_output", ""),
            "tags": eval_case.get("tags", []),
            "status": "completed",
        }

    except subprocess.TimeoutExpired:
        return {
            "eval_id": eval_id,
            "skill_name": skill_name,
            "prompt": prompt,
            "transcript": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "exit_code": -1,
            "duration_s": timeout,
            "success": False,
            "expectations": eval_case.get("expectations", []),
            "expected_output": eval_case.get("expected_output", ""),
            "tags": eval_case.get("tags", []),
            "status": "timeout",
        }
    except FileNotFoundError:
        elapsed = time.time() - start
        return {
            "eval_id": eval_id,
            "skill_name": skill_name,
            "prompt": prompt,
            "transcript": "",
            "stderr": "claude CLI not found in PATH. Install: https://docs.anthropic.com/claude-code",
            "exit_code": -1,
            "duration_s": round(elapsed, 2),
            "success": False,
            "expectations": eval_case.get("expectations", []),
            "expected_output": eval_case.get("expected_output", ""),
            "tags": eval_case.get("tags", []),
            "status": "error",
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "eval_id": eval_id,
            "skill_name": skill_name,
            "prompt": prompt,
            "transcript": "",
            "stderr": str(e)[:500],
            "exit_code": -1,
            "duration_s": round(elapsed, 2),
            "success": False,
            "expectations": eval_case.get("expectations", []),
            "expected_output": eval_case.get("expected_output", ""),
            "tags": eval_case.get("tags", []),
            "status": "error",
        }


def load_evals(evals_path: str) -> dict:
    """Load and validate evals.json file.

    Args:
        evals_path: Absolute path to evals.json.

    Returns:
        Parsed evals data with skill_name, version, and evals list.

    Raises:
        SystemExit: If file not found or invalid.
    """
    path = Path(evals_path).expanduser()
    if not path.exists():
        print(json.dumps({"error": f"evals.json not found at {path}"}))
        sys.exit(1)

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON in {path}: {e}"}))
        sys.exit(1)

    if "evals" not in data or not isinstance(data["evals"], list):
        print(json.dumps({"error": "evals.json must contain an 'evals' array"}))
        sys.exit(1)

    return data


def filter_by_tags(test_cases: list[dict], include_tags: list[str]) -> list[dict]:
    """Filter test cases by tag inclusion.

    Args:
        test_cases: List of eval case dicts.
        include_tags: Only run cases that have at least one of these tags.

    Returns:
        Filtered list of test cases.
    """
    if not include_tags:
        return test_cases
    return [tc for tc in test_cases if any(tag in tc.get("tags", []) for tag in include_tags)]


def main():
    parser = argparse.ArgumentParser(
        description="Skill evaluation executor -- spawns claude -p subprocesses"
    )
    parser.add_argument("--skill", required=True, help="Skill name to evaluate")
    parser.add_argument(
        "--evals-path", help="Path to evals.json (default: ~/.claude/skills/<skill>/evals.json)"
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Number of parallel workers (default: 3)"
    )
    parser.add_argument(
        "--timeout", type=int, default=120, help="Per-eval timeout in seconds (default: 120)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--tags", default="", help="Comma-separated tags to filter eval cases (default: run all)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be run without executing"
    )
    args = parser.parse_args()

    # Resolve evals.json path
    evals_path = args.evals_path or os.path.expanduser(f"~/.claude/skills/{args.skill}/evals.json")

    # Load and validate
    evals_data = load_evals(evals_path)
    skill_name = evals_data.get("skill_name", args.skill)
    version = evals_data.get("version", "unknown")
    test_cases = evals_data.get("evals", [])

    # Filter by tags if specified
    include_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if include_tags:
        test_cases = filter_by_tags(test_cases, include_tags)
        print(
            f"Filtered to {len(test_cases)} eval(s) matching tags: {include_tags}", file=sys.stderr
        )

    if not test_cases:
        print(json.dumps({"error": "No test cases found (after filtering)"}))
        sys.exit(1)

    # Dry run mode
    if args.dry_run:
        print(f"Dry run for {skill_name} v{version}:", file=sys.stderr)
        for tc in test_cases:
            tags_str = ", ".join(tc.get("tags", []))
            print(
                f"  eval-{tc.get('id', '?')}: {tc.get('prompt', '')[:60]}... [{tags_str}]",
                file=sys.stderr,
            )
        print(f"\nTotal: {len(test_cases)} eval(s), {args.workers} worker(s)", file=sys.stderr)
        return

    # Execute evaluations
    print(
        f"Running {len(test_cases)} eval(s) for {skill_name} v{version} "
        f"with {args.workers} worker(s), timeout={args.timeout}s...",
        file=sys.stderr,
    )

    results = []
    total_start = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_single_eval, tc, skill_name, args.timeout): tc for tc in test_cases
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status_icon = "[PASS]" if result["success"] else "[FAIL]"
            print(
                f"  {status_icon} eval-{result['eval_id']}: "
                f"{result['duration_s']}s ({result['status']})",
                file=sys.stderr,
            )

    total_duration = round(time.time() - total_start, 2)

    # Sort by eval_id for consistent output
    results.sort(key=lambda r: r["eval_id"])

    # Build output
    passed = sum(1 for r in results if r["success"])
    failed = sum(1 for r in results if not r["success"])

    output = {
        "skill_name": skill_name,
        "version": version,
        "evals_path": str(evals_path),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(results), 4) if results else 0,
        "total_duration_s": total_duration,
        "workers": args.workers,
        "timeout": args.timeout,
        "results": results,
    }

    output_str = json.dumps(output, indent=2, ensure_ascii=False)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output_str)
        print(f"\nResults written to {output_path}", file=sys.stderr)
    else:
        print(output_str)

    # Summary
    print(
        f"\nSummary: {passed}/{len(results)} passed "
        f"({output['pass_rate']:.0%}) in {total_duration}s",
        file=sys.stderr,
    )

    # Exit with non-zero if any failures
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
