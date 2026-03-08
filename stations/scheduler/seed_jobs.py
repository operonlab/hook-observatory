#!/usr/bin/env python3
"""Seed Cronicle with scheduled jobs from manifest.json + crontab.

Reads schedules/manifest.json and creates Cronicle events via REST API.
Idempotent: skips events whose title already exists.

Usage:
    python3 stations/scheduler/seed_jobs.py [--api-key KEY] [--dry-run]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CRONICLE_URL = "http://127.0.0.1:4105"
DEFAULT_API_KEY = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
MANIFEST = Path(__file__).resolve().parent.parent.parent / "schedules" / "manifest.json"


# ── Category mapping ──────────────────────────────────────

CATEGORY_MAP: dict[str, str] = {}  # filled at runtime from API


def api_call(endpoint: str, data: dict, api_key: str) -> dict:
    """POST to Cronicle API and return JSON response."""
    url = f"{CRONICLE_URL}/api/app/{endpoint}?api_key={api_key}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read())


def get_categories(api_key: str) -> dict[str, str]:
    """Return {title: id} mapping of categories."""
    return CATEGORY_MAP


def get_existing_events(api_key: str) -> set[str]:
    """Return set of existing event titles."""
    result = api_call("get_schedule", {}, api_key)
    return {ev.get("title", "") for ev in result.get("rows", [])}


def manifest_to_cron(schedule: dict) -> dict:
    """Convert manifest schedule to Cronicle timing object."""
    if "calendar" in schedule:
        cal = schedule["calendar"]
        timing = {"minutes": [cal.get("Minute", 0)]}

        if "Hour" in cal:
            timing["hours"] = [cal["Hour"]]
        if "Weekday" in cal:
            timing["weekdays"] = [cal["Weekday"]]
        if "Day" in cal:
            timing["days"] = [cal["Day"]]

        return timing

    if "interval" in schedule:
        secs = schedule["interval"]
        # 259200s = 3 days
        if secs == 259200:
            # every 3 days at midnight
            return {"days": [1, 4, 7, 10, 13, 16, 19, 22, 25, 28], "hours": [0], "minutes": [0]}
        # Fallback: daily
        return {"hours": [0], "minutes": [0]}

    return {"hours": [0], "minutes": [0]}


def build_event(job: dict, category_id: str, plugin_id: str) -> dict:
    """Build a Cronicle event from a manifest job."""
    timing = manifest_to_cron(job["schedule"])

    event = {
        "title": job["name"],
        "enabled": 1 if job.get("enabled", True) else 0,
        "category": category_id,
        "plugin": plugin_id,
        "target": "allgrp",
        "timing": timing,
        "timezone": "Asia/Taipei",
        "max_children": 1,
        "timeout": 3600,
        "catch_up": 1,
        "queue_max": 1,
        "notify_fail": "",
        "notify_success": "",
        "notes": job.get("description", ""),
        "params": {
            "script": f"#!/bin/bash\n{job['command']}",
            "annotate": 1,
            "json": 0,
        },
    }
    return event


def build_http_event(name: str, url: str, method: str, category_id: str, plugin_id: str,
                     timing: dict, description: str = "") -> dict:
    """Build a Cronicle HTTP Request event."""
    return {
        "title": name,
        "enabled": 1,
        "category": category_id,
        "plugin": plugin_id,
        "target": "allgrp",
        "timing": timing,
        "timezone": "Asia/Taipei",
        "max_children": 1,
        "timeout": 300,
        "catch_up": 1,
        "queue_max": 1,
        "notes": description,
        "params": {
            "method": method,
            "url": url,
            "headers": "User-Agent: Cronicle/Workshop",
            "data": "",
            "timeout": "60",
            "follow": 1,
            "ssl_cert_bypass": 0,
            "success_match": "",
            "error_match": "",
        },
    }


def seed_manifest_jobs(api_key: str, dry_run: bool = False) -> int:
    """Seed jobs from manifest.json. Returns count of created events."""
    manifest = json.loads(MANIFEST.read_text())
    jobs = manifest.get("jobs", [])

    # Get existing events
    existing = get_existing_events(api_key)
    print(f"Existing events: {len(existing)}")

    # Shell plugin ID
    shell_plugin = "shellplug"
    url_plugin = "urlplug"

    created = 0

    for job in jobs:
        # Skip disabled legacy jobs
        if not job.get("enabled", True):
            continue

        # Skip daemons — they stay on launchd
        if job.get("type") == "daemon":
            continue

        name = job["name"]

        if name in existing:
            print(f"  SKIP (exists): {name}")
            continue

        # Use 'general' as fallback category ID
        category_id = "general"

        # Special case: ws-finance-billing uses HTTP plugin
        if name == "ws-finance-billing":
            event = build_http_event(
                name=name,
                url="http://127.0.0.1:8801/api/finance/billing/process?space_id=default",
                method="POST",
                category_id=category_id,
                plugin_id=url_plugin,
                timing=manifest_to_cron(job["schedule"]),
                description=job.get("description", ""),
            )
        else:
            event = build_event(job, category_id, shell_plugin)

        if dry_run:
            print(f"  DRY-RUN: would create '{name}'")
            print(f"    timing: {event['timing']}")
            created += 1
            continue

        try:
            result = api_call("create_event", event, api_key)
            if result.get("code") == 0:
                print(f"  CREATED: {name} (id={result.get('id')})")
                created += 1
            else:
                print(f"  ERROR: {name} — {result.get('description', 'unknown')}", file=sys.stderr)
        except urllib.error.HTTPError as e:
            print(f"  ERROR: {name} — HTTP {e.code}", file=sys.stderr)

    return created


def seed_crontab_jobs(api_key: str, dry_run: bool = False) -> int:
    """Seed the crontab job (kas-memory-sync)."""
    existing = get_existing_events(api_key)
    shell_plugin = "shellplug"
    category_id = "general"

    name = "kas-memory-sync"
    if name in existing:
        print(f"  SKIP (exists): {name}")
        return 0

    event = {
        "title": name,
        "enabled": 1,
        "category": category_id,
        "plugin": shell_plugin,
        "target": "allgrp",
        "timing": {"hours": [0, 6, 12, 18], "minutes": [0]},
        "timezone": "Asia/Taipei",
        "max_children": 1,
        "timeout": 3600,
        "catch_up": 1,
        "queue_max": 1,
        "notes": "KAS Memory V1→V2 sync (every 6 hours)",
        "params": {
            "script": (
                "#!/bin/bash\n"
                "/Users/joneshong/.local/bin/python3"
                " /Users/joneshong/Claude/projects/kas-memory/scripts/scan-and-sync.py"
                " --recent 7"
            ),
            "annotate": 1,
            "json": 0,
        },
    }

    if dry_run:
        print(f"  DRY-RUN: would create '{name}'")
        return 1

    try:
        result = api_call("create_event", event, api_key)
        if result.get("code") == 0:
            print(f"  CREATED: {name} (id={result.get('id')})")
            return 1
        else:
            print(f"  ERROR: {name} — {result.get('description', 'unknown')}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"  ERROR: {name} — HTTP {e.code}", file=sys.stderr)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Cronicle with Workshop scheduled jobs")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Cronicle API key")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created")
    args = parser.parse_args()

    print("=" * 60)
    print("Cronicle Job Seeder — Workshop Scheduler")
    print("=" * 60)

    print("\n[1/2] Seeding manifest.json jobs...")
    m_count = seed_manifest_jobs(args.api_key, args.dry_run)

    print("\n[2/2] Seeding crontab jobs...")
    c_count = seed_crontab_jobs(args.api_key, args.dry_run)

    total = m_count + c_count
    print(f"\nDone! Created {total} events.")

    if args.dry_run:
        print("(dry-run mode — no changes made)")


if __name__ == "__main__":
    main()
