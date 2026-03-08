#!/Users/joneshong/.local/bin/python3
"""Skill lifecycle automation runner.

Runs headless phases of the skill lifecycle pipeline:
  Phase 2: Test (T1-T4)
  Phase 3: Security (S1-S3)
  Phase 6: Catalog
Then posts all results to Anvil API for persistence.

Usage:
    python3 ws_skill_lifecycle.py [--trigger manual|cron|api] [--dry-run]

Phases 1 (Audit), 4 (Optimize), 5 (Publish) require LLM — skipped in automation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Full paths for sandbox/cron compatibility
PYTHON = str(Path.home() / ".local" / "bin" / "python3")
SKILLS_DIR = Path.home() / ".claude" / "skills"
TESTER_SCRIPT = SKILLS_DIR / "skill-tester" / "scripts" / "run_all.py"
SECURITY_SCRIPT = SKILLS_DIR / "skill-security-scan" / "scripts" / "security-scan.py"
CATALOG_SCRIPT = SKILLS_DIR / "skill-catalog" / "scripts" / "extract_catalog.py"
ANVIL_URL = "http://127.0.0.1:4103"

# LLM-only phases, always skipped in automation
SKIPPED_PHASES = ["audit", "optimize", "publish"]


def run_cmd(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run command and return (rc, stdout, stderr)."""
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except Exception as e:
        return -3, "", str(e)


def run_tests() -> dict[str, Any]:
    """Phase 2: Run T1-T4 structural tests."""
    phase = {"status": "ok", "duration_ms": 0}
    start = time.time()

    if not TESTER_SCRIPT.exists():
        phase["status"] = "failed"
        phase["detail"] = f"Script not found: {TESTER_SCRIPT}"
        return phase

    rc, stdout, stderr = run_cmd(
        [PYTHON, str(TESTER_SCRIPT), "--format", "json"],
        timeout=120,
    )

    phase["duration_ms"] = int((time.time() - start) * 1000)

    if rc != 0:
        # run_all.py may exit non-zero if skills fail, but still produce output
        if not stdout.strip():
            phase["status"] = "failed"
            phase["detail"] = stderr[:500] if stderr else "no output"
            return phase

    try:
        results = json.loads(stdout)
        phase["results"] = results
    except json.JSONDecodeError:
        # Try to parse line-by-line JSON (some scripts output JSONL)
        phase["results"] = {"raw": stdout[:5000]}

    return phase


def run_security() -> dict[str, Any]:
    """Phase 3: Run S1-S3 security scan."""
    phase = {"status": "ok", "duration_ms": 0}
    start = time.time()

    if not SECURITY_SCRIPT.exists():
        phase["status"] = "failed"
        phase["detail"] = f"Script not found: {SECURITY_SCRIPT}"
        return phase

    rc, stdout, stderr = run_cmd(
        [PYTHON, str(SECURITY_SCRIPT), "--batch", "--json"],
        timeout=120,
    )

    phase["duration_ms"] = int((time.time() - start) * 1000)

    if rc != 0 and not stdout.strip():
        phase["status"] = "failed"
        phase["detail"] = stderr[:500] if stderr else "no output"
        return phase

    try:
        results = json.loads(stdout)
        phase["results"] = results
    except json.JSONDecodeError:
        phase["results"] = {"raw": stdout[:5000]}

    return phase


def run_catalog() -> dict[str, Any]:
    """Phase 6: Generate skill catalog."""
    phase = {"status": "ok", "duration_ms": 0}
    start = time.time()

    if not CATALOG_SCRIPT.exists():
        phase["status"] = "failed"
        phase["detail"] = f"Script not found: {CATALOG_SCRIPT}"
        return phase

    rc, stdout, stderr = run_cmd(
        [PYTHON, str(CATALOG_SCRIPT)],
        timeout=60,
    )

    phase["duration_ms"] = int((time.time() - start) * 1000)

    if rc != 0:
        phase["status"] = "failed"
        phase["detail"] = stderr[:500] if stderr else "unknown error"
        return phase

    try:
        catalog = json.loads(stdout)
        phase["results"] = {
            "total_skills": len(catalog) if isinstance(catalog, list) else catalog.get("total", 0),
        }
    except json.JSONDecodeError:
        phase["results"] = {"raw_length": len(stdout)}

    return phase


def extract_test_metrics(test_phase: dict) -> dict[str, Any]:
    """Extract test metrics from test phase results."""
    results = test_phase.get("results", {})

    # run_all.py --format json outputs: {"meta": {...}, "skills": {"name": {"tests": {...}, ...}}}
    skills_data = results.get("skills", {})

    # skills_data can be dict (name→data) or list
    if isinstance(skills_data, dict):
        skill_items = [(name, data) for name, data in skills_data.items()]
    elif isinstance(skills_data, list):
        skill_items = [(s.get("skill_name", s.get("name", "unknown")), s) for s in skills_data]
    else:
        skill_items = []

    total = len(skill_items)
    passed = 0
    partial = 0
    failed = 0
    test_details = []

    for name, data in skill_items:
        tests = data.get("tests", {})
        # Determine overall skill status from individual test results
        statuses = (
            [t.get("status", "PASS") for t in tests.values()] if isinstance(tests, dict) else []
        )
        if not statuses or all(s == "PASS" for s in statuses):
            skill_status = "pass"
            passed += 1
        elif any(s == "FAIL" for s in statuses):
            skill_status = "fail"
            failed += 1
        else:
            skill_status = "partial"
            partial += 1

        # Build checks list
        checks = []
        if isinstance(tests, dict):
            for test_id, test_data in tests.items():
                issues = test_data.get("issues", [])
                checks.append(
                    {
                        "id": test_id,
                        "name": test_id,
                        "passed": test_data.get("status") == "PASS",
                        "detail": "; ".join(
                            i.get("message", str(i)) if isinstance(i, dict) else str(i)
                            for i in issues
                        )
                        if issues
                        else "OK",
                    }
                )

        test_details.append(
            {
                "skill_name": name,
                "status": skill_status,
                "checks": checks,
            }
        )

    return {
        "total_skills": total,
        "test_passed": passed,
        "test_partial": partial,
        "test_failed": failed,
        "test_details": test_details,
    }


def extract_security_metrics(sec_phase: dict) -> dict[str, Any]:
    """Extract security metrics from security phase results."""
    results = sec_phase.get("results", {})

    # security-scan.py --batch --json outputs: list of {skill, result, findings, ...}
    if isinstance(results, list):
        skills = results
    elif isinstance(results, dict):
        skills = results.get("skills", results.get("results", []))
    else:
        skills = []

    clean = sum(1 for s in skills if s.get("result") == "PASS" and not s.get("findings"))
    warned = sum(1 for s in skills if s.get("result") == "WARN")
    blocked = sum(1 for s in skills if s.get("result") == "BLOCK")

    security_details = []
    for s in skills:
        name = s.get("skill", s.get("skill_name", s.get("name", "unknown")))
        findings = s.get("findings", [])
        if s.get("result") == "BLOCK":
            status = "block"
        elif findings:
            status = "warn"
        else:
            status = "clean"
        security_details.append(
            {
                "skill_name": name,
                "status": status,
                "findings": [
                    {
                        "id": f.get("id", f.get("category", "")),
                        "severity": f.get("severity", ""),
                        "pattern": f.get("pattern", f.get("description", "")),
                        "line": f.get("line", 0),
                        "context": f.get("context", f.get("match", "")),
                    }
                    for f in findings[:10]
                ],
            }
        )

    return {
        "sec_clean": clean or len(skills),
        "sec_warned": warned,
        "sec_blocked": blocked,
        "security_details": security_details,
    }


def post_to_anvil(run_data: dict, dry_run: bool = False) -> str | None:
    """POST lifecycle run results to Anvil API. Returns run_id or None."""
    if dry_run:
        print(json.dumps(run_data, indent=2, ensure_ascii=False, default=str))
        return run_data.get("run_id")

    try:
        import urllib.error
        import urllib.request

        # Step 1: Create run
        create_body = json.dumps(
            {
                "trigger": run_data["trigger"],
                "skipped_phases": SKIPPED_PHASES,
            }
        ).encode()

        req = urllib.request.Request(  # noqa: S310
            f"{ANVIL_URL}/api/anvil/lifecycle/runs",
            data=create_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            created = json.loads(resp.read())
            run_id = created["run_id"]

        # Step 2: Update with results
        update_body = json.dumps(
            {
                "status": run_data["status"],
                "completed_at": run_data["completed_at"],
                "phases": run_data["phases"],
                "total_skills": run_data.get("total_skills", 0),
                "test_passed": run_data.get("test_passed", 0),
                "test_partial": run_data.get("test_partial", 0),
                "test_failed": run_data.get("test_failed", 0),
                "sec_clean": run_data.get("sec_clean", 0),
                "sec_warned": run_data.get("sec_warned", 0),
                "sec_blocked": run_data.get("sec_blocked", 0),
                "test_details": run_data.get("test_details"),
                "security_details": run_data.get("security_details"),
                "catalog_snapshot": run_data.get("catalog_snapshot"),
                "errors": run_data.get("errors", {}),
            }
        ).encode()

        req = urllib.request.Request(  # noqa: S310
            f"{ANVIL_URL}/api/anvil/lifecycle/runs/{run_id}",
            data=update_body,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            resp.read()

        return run_id

    except Exception as e:
        print(f"Warning: Failed to post to Anvil: {e}", file=sys.stderr)
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Skill lifecycle automation runner")
    parser.add_argument("--trigger", default="manual", choices=["manual", "cron", "api"])
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without posting to Anvil"
    )
    args = parser.parse_args()

    print(f"[{datetime.now().isoformat()}] Starting skill lifecycle automation...")
    print(f"  Trigger: {args.trigger}")
    print(f"  Skipped phases: {', '.join(SKIPPED_PHASES)}")

    run_data: dict[str, Any] = {
        "run_id": f"lifecycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "trigger": args.trigger,
        "status": "running",
        "phases": {},
        "errors": {},
    }

    # Phase 2: Test
    print("\n--- Phase 2: Test ---")
    test_phase = run_tests()
    run_data["phases"]["test"] = {
        "status": test_phase["status"],
        "duration_ms": test_phase.get("duration_ms", 0),
    }
    if test_phase["status"] == "ok":
        metrics = extract_test_metrics(test_phase)
        run_data.update(metrics)
        print(
            f"  Total: {metrics['total_skills']}, Pass: {metrics['test_passed']}, "
            f"Partial: {metrics['test_partial']}, Fail: {metrics['test_failed']}"
        )
    else:
        run_data["errors"]["test"] = test_phase.get("detail", "unknown error")
        print(f"  FAILED: {test_phase.get('detail', 'unknown')}")

    # Phase 3: Security
    print("\n--- Phase 3: Security ---")
    sec_phase = run_security()
    run_data["phases"]["security"] = {
        "status": sec_phase["status"],
        "duration_ms": sec_phase.get("duration_ms", 0),
    }
    if sec_phase["status"] == "ok":
        sec_metrics = extract_security_metrics(sec_phase)
        run_data.update(sec_metrics)
        print(
            f"  Clean: {sec_metrics['sec_clean']}, Warn: {sec_metrics['sec_warned']}, "
            f"Block: {sec_metrics['sec_blocked']}"
        )
    else:
        run_data["errors"]["security"] = sec_phase.get("detail", "unknown error")
        print(f"  FAILED: {sec_phase.get('detail', 'unknown')}")

    # Phase 6: Catalog
    print("\n--- Phase 6: Catalog ---")
    catalog_phase = run_catalog()
    run_data["phases"]["catalog"] = {
        "status": catalog_phase["status"],
        "duration_ms": catalog_phase.get("duration_ms", 0),
    }
    if catalog_phase["status"] == "ok":
        catalog_results = catalog_phase.get("results", {})
        run_data["catalog_snapshot"] = catalog_results
        print(f"  Skills cataloged: {catalog_results.get('total_skills', '?')}")
    else:
        run_data["errors"]["catalog"] = catalog_phase.get("detail", "unknown error")
        print(f"  FAILED: {catalog_phase.get('detail', 'unknown')}")

    # Mark skipped phases
    for phase in SKIPPED_PHASES:
        run_data["phases"][phase] = {"status": "skipped"}

    # Determine overall status
    errors = run_data.get("errors", {})
    if not errors:
        run_data["status"] = "completed"
    elif len(errors) == 3:  # All phases failed
        run_data["status"] = "failed"
    else:
        run_data["status"] = "partial"

    run_data["completed_at"] = datetime.now().isoformat()

    # Post to Anvil
    print("\n--- Posting to Anvil ---")
    run_id = post_to_anvil(run_data, dry_run=args.dry_run)
    if run_id:
        print(f"  Lifecycle run saved: {run_id}")
    else:
        print("  Warning: Could not save to Anvil (server may be offline)")
        # Fallback: print JSON for manual inspection
        print(json.dumps(run_data, indent=2, ensure_ascii=False, default=str))

    print(f"\n[{datetime.now().isoformat()}] Lifecycle automation complete: {run_data['status']}")
    sys.exit(0 if run_data["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
