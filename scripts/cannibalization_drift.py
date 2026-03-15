#!/usr/bin/env python3
"""
cannibalization_drift.py — Check upstream drift for cannibalized sources.

For each source in vendor/cannibalization.json:
  - github_tags:    compare pinned version vs latest GitHub tag
  - github_commits: compare pinned commit date vs latest commit date
  - manual:         skip (human-reviewed sources like papers/articles)

Updates cannibalization.json in-place with latest drift info.
Outputs summary to stdout (for Cronicle log capture).

Usage:
    python3 scripts/cannibalization_drift.py [--dry-run] [--notify]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MANIFEST_PATH = Path(__file__).parent.parent / "vendor" / "cannibalization.json"
GITHUB_API = "https://api.github.com"
TIMEOUT = 15


def github_get(path: str) -> dict | list | None:
    """GET from GitHub API. Returns parsed JSON or None on error."""
    url = f"{GITHUB_API}{path}"
    req = Request(  # noqa: S310
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "workshop-drift-checker"},
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            return json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"  [WARN] GitHub API error for {path}: {e}", file=sys.stderr)
        return None


def check_github_tags(source: dict) -> dict:
    """Check latest tag for a GitHub repo source."""
    ref = source.get("upstream_ref")
    if not ref:
        return {"drift_level": "unknown", "error": "no upstream_ref"}

    data = github_get(f"/repos/{ref}/tags?per_page=1")
    if not data:
        return {"drift_level": "unknown", "error": "API call failed"}

    if not data:  # empty array = no tags
        return {"drift_level": "unknown", "error": "no tags found"}

    latest_tag = data[0]["name"]
    pinned_version = source.get("pinned_at", {}).get("version")

    if not pinned_version:
        return {
            "latest_upstream": latest_tag,
            "drift_level": "unknown",
            "note": "no pinned version to compare",
        }

    # Normalize: strip leading 'v' for comparison
    norm_pinned = pinned_version.lstrip("v")
    norm_latest = latest_tag.lstrip("v")

    if norm_pinned == norm_latest:
        drift_level = "none"
    else:
        # Simple heuristic: split by dots, compare major
        try:
            pinned_parts = [int(x) for x in norm_pinned.split(".")]
            latest_parts = [int(x) for x in norm_latest.split(".")]
            if latest_parts[0] > pinned_parts[0]:
                drift_level = "major"
            else:
                drift_level = "minor"
        except (ValueError, IndexError):
            # Non-semver: any difference = minor
            drift_level = "minor"

    return {"latest_upstream": latest_tag, "drift_level": drift_level}


def check_github_commits(source: dict) -> dict:
    """Check latest commit for a GitHub repo source."""
    ref = source.get("upstream_ref")
    if not ref:
        return {"drift_level": "unknown", "error": "no upstream_ref"}

    data = github_get(f"/repos/{ref}/commits?per_page=1")
    if not data:
        return {"drift_level": "unknown", "error": "API call failed"}

    if not data:
        return {"drift_level": "unknown", "error": "no commits found"}

    latest_sha = data[0]["sha"][:7]
    latest_date = data[0]["commit"]["committer"]["date"][:10]  # YYYY-MM-DD
    pinned_commit = source.get("pinned_at", {}).get("commit")
    pinned_date = source.get("pinned_at", {}).get("date")

    if pinned_commit and latest_sha == pinned_commit[:7]:
        drift_level = "none"
    elif pinned_date:
        # Calculate days since pinned
        try:
            days = (
                datetime.strptime(latest_date, "%Y-%m-%d")
                - datetime.strptime(pinned_date, "%Y-%m-%d")
            ).days
            if days <= 7:
                drift_level = "none"
            elif days <= 90:
                drift_level = "minor"
            else:
                drift_level = "major"
        except ValueError:
            drift_level = "minor"
    else:
        drift_level = "unknown"

    return {
        "latest_upstream": f"{latest_sha} ({latest_date})",
        "drift_level": drift_level,
    }


def send_notification(summary: str) -> None:
    """Send drift summary via Bark notification."""
    from urllib.parse import quote

    try:
        encoded = quote(summary, safe="")
        subprocess.run(  # noqa: S603
            [
                "/usr/bin/curl",
                "-s",
                f"http://127.0.0.1:8090/workshop/{quote('蠶食漂移偵測', safe='')}/{encoded}",
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:  # noqa: S110
        pass  # Best-effort notification


def main() -> int:
    parser = argparse.ArgumentParser(description="Check cannibalization upstream drift")
    parser.add_argument("--dry-run", action="store_true", help="Check but don't update manifest")
    parser.add_argument("--notify", action="store_true", help="Send Bark notification on drift")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"ERROR: Manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text())
    today = datetime.now().strftime("%Y-%m-%d")
    results = []
    drift_detected = False

    for source in manifest.get("sources", []):
        sid = source["id"]
        check_method = source.get("drift", {}).get("check_method", "manual")
        stype = source.get("type", "repo")

        if check_method == "manual":
            print(f"  [{sid}] type={stype} — manual check, skipping")
            results.append((sid, "skip", "manual"))
            continue

        print(f"  [{sid}] checking via {check_method}...")

        if check_method == "github_tags":
            result = check_github_tags(source)
        elif check_method == "github_commits":
            result = check_github_commits(source)
        else:
            print(f"  [{sid}] unknown check_method: {check_method}")
            results.append((sid, "error", f"unknown method {check_method}"))
            continue

        # Update drift info
        drift = source.setdefault("drift", {})
        drift["latest_checked"] = today
        drift["check_method"] = check_method
        if "latest_upstream" in result:
            drift["latest_upstream"] = result["latest_upstream"]
        drift["drift_level"] = result["drift_level"]

        level = result["drift_level"]
        upstream = result.get("latest_upstream", "?")
        pinned = (
            source.get("pinned_at", {}).get("version")
            or source.get("pinned_at", {}).get("commit")
            or "?"
        )

        if level in ("minor", "major"):
            drift_detected = True
            print(f"  [{sid}] ⚠ {level.upper()} drift: pinned={pinned} → upstream={upstream}")
        elif level == "none":
            print(f"  [{sid}] ✓ no drift (pinned={pinned})")
        else:
            print(f"  [{sid}] ? drift unknown")

        results.append((sid, level, upstream))

    # Update manifest
    if not args.dry_run:
        manifest["updated_at"] = today
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        print(f"\nManifest updated: {MANIFEST_PATH}")
    else:
        print("\n[DRY-RUN] Manifest not updated")

    # Summary
    print("\n── Drift Summary ──")
    for sid, level, detail in results:
        icon = {
            "none": "✓",
            "minor": "⚡",
            "major": "🔴",
            "skip": "⏭",
            "error": "❌",
            "unknown": "?",
        }.get(level, "?")
        print(f"  {icon} {sid}: {level} ({detail})")

    # Notification
    if args.notify and drift_detected:
        drifted = [sid for sid, level, _ in results if level in ("minor", "major")]
        send_notification(f"漂移: {', '.join(drifted)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
