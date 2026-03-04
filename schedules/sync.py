#!/usr/bin/env python3
"""
sync.py — Synchronize workshop schedules manifest to launchd via scheduler skill

Reads schedules/manifest.json, diffs against scheduler registry,
and adds/removes jobs to keep them in sync.

Usage:
    python3 ~/workshop/schedules/sync.py            # sync
    python3 ~/workshop/schedules/sync.py --dry-run  # preview changes
    python3 ~/workshop/schedules/sync.py --force    # remove all jobs, re-add from manifest
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
MANIFEST = SCRIPT_DIR / "manifest.json"
SCHEDULER = SCRIPT_DIR / "scheduler.py"
PYTHON = Path.home() / ".local/bin/python3"
REGISTRY = Path.home() / "workshop/outputs/scheduler/registry.json"


def load_manifest_jobs() -> list[dict]:
    """Load enabled jobs from manifest.json."""
    with open(MANIFEST) as f:
        data = json.load(f)
    return [job for job in data.get("jobs", []) if job.get("enabled", False)]


def load_registry_names() -> list[str]:
    """Load job names from registry.json."""
    if not REGISTRY.exists():
        return []
    with open(REGISTRY) as f:
        data = json.load(f)
    if isinstance(data, list):
        return [entry["name"] for entry in data if "name" in entry]
    return []


def run_scheduler(args: list[str]) -> bool:
    """Run scheduler.py with given args. Returns True on success."""
    cmd = [str(PYTHON), str(SCHEDULER)] + args
    result = subprocess.run(cmd)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize workshop schedules manifest to launchd",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove all jobs then re-add from manifest",
    )
    args = parser.parse_args()

    # Validate dependencies
    if not MANIFEST.exists():
        print(f"[error] Manifest not found: {MANIFEST}", file=sys.stderr)
        sys.exit(1)

    if not SCHEDULER.exists():
        print(f"[error] Scheduler script not found: {SCHEDULER}", file=sys.stderr)
        sys.exit(1)

    mode_str = "DRY RUN" if args.dry_run else "LIVE"
    if args.force:
        mode_str += " + FORCE"

    print("Workshop Schedule Sync")
    print(f"  Manifest : {MANIFEST}")
    print(f"  Registry : {REGISTRY}")
    print(f"  Mode     : {mode_str}")
    print()

    # Load manifest enabled jobs
    manifest_jobs = load_manifest_jobs()
    manifest_names = [job["name"] for job in manifest_jobs]

    # Load registry jobs
    registry_names = load_registry_names()

    print(f"  Manifest jobs (enabled): {' '.join(manifest_names) if manifest_names else 'none'}")
    print(f"  Registry jobs          : {' '.join(registry_names) if registry_names else 'none'}")
    print()

    # Calculate diff
    to_add: list[str] = []
    to_remove: list[str] = []

    # Jobs in manifest but not in registry → add
    for name in manifest_names:
        if name not in registry_names or args.force:
            to_add.append(name)

    # Jobs in registry but not in manifest → remove
    for name in registry_names:
        if name not in manifest_names or args.force:
            to_remove.append(name)

    if not to_add and not to_remove:
        print("[OK] Already in sync — no changes needed.")
        sys.exit(0)

    print("Changes:")
    for name in to_remove:
        print(f"  - REMOVE: {name}")
    for name in to_add:
        print(f"  + ADD:    {name}")
    print()

    if args.dry_run:
        print("[dry-run] No changes applied.")
        sys.exit(0)

    # Build a lookup of manifest jobs by name
    manifest_by_name = {job["name"]: job for job in manifest_jobs}

    # Apply removals first
    for name in to_remove:
        print(f"[remove] {name}")
        run_scheduler(["remove", name])  # ignore errors, matching shell behavior

    # Apply additions
    for name in to_add:
        job = manifest_by_name.get(name)
        if not job:
            print(f"[skip] {name} — not found in manifest enabled jobs", file=sys.stderr)
            continue

        command = job.get("command", "")
        schedule = json.dumps(job.get("schedule", {}))
        description = job.get("description", "")

        print(f"[add] {name} → {command}")
        run_scheduler(["add", name, command, schedule, description])

    print()
    print("[OK] Sync complete.")


if __name__ == "__main__":
    main()
