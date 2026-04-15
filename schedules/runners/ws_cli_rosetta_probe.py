#!/usr/bin/env python3
"""Daily CLI dictionary probe — detect version drift + auto-update + report.

Replaces ws_cli_rosetta_check.py (weekly → daily, passive → active).

Flow:
1. check_all_versions() → installed vs remote
2. Compare with state.json
3. On drift → probe_help() + auto-update known_version
4. Bark notify + write report
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Bootstrap cli-rosetta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "libs" / "cli-rosetta"))

from cli_rosetta.probe import check_all_versions, parse_help_flags, probe_cli
from cli_rosetta.registry import get, list_entries
from cli_rosetta.state import get_help_flags, load, save, update_version
from cli_rosetta.updater import apply_probe_report

REPORT_FILE = Path(f"/tmp/cli-rosetta-probe-{datetime.now(UTC).strftime('%Y%m%d')}.json")
HEALTH_FILE = Path("/tmp/cli-rosetta-health.json")


def main() -> None:
    state = load()
    versions = check_all_versions()

    # Snapshot help flags for ALL CLIs (baseline for future diff)
    for entry in list_entries():
        current_flags = parse_help_flags(entry.binary)
        update_version(
            state,
            entry.name,
            installed=next((v.installed for v in versions if v.cli_name == entry.name), ""),
            remote=next((v.remote for v in versions if v.cli_name == entry.name), ""),
            help_flags=current_flags,
        )

    # Write health file (for sentinel / dashboard)
    health = {
        "checked_at": datetime.now(UTC).isoformat(),
        "results": [
            {
                "name": v.cli_name,
                "installed": v.installed,
                "remote": v.remote,
                "known": v.known,
                "drift": v.has_drift,
                "entry_stale": v.entry_stale,
            }
            for v in versions
        ],
    }
    HEALTH_FILE.write_text(json.dumps(health, indent=2, ensure_ascii=False))

    # Detect drift
    drifted = [v for v in versions if v.has_drift]
    probed = []

    for v in drifted:
        print(f"⚡ Drift: {v.cli_name} installed={v.installed} remote={v.remote}")
        try:
            entry = get(v.cli_name)
            prev_flags = get_help_flags(state, v.cli_name)
            report = probe_cli(entry, v.remote, previous_flags=prev_flags)
            result = apply_probe_report(report)
            probed.append(
                {
                    **report.to_dict(),
                    "update_result": result,
                }
            )
            print(f"  → updated: {result['updated']}")
            if result["pending"]:
                print(f"  → pending review: {result['pending']}")
        except Exception as e:
            print(f"  → probe failed: {e}")
            probed.append({"cli_name": v.cli_name, "error": str(e)})

    # Save state
    save(state)

    # Write probe report
    report_data = {
        "probed_at": datetime.now(UTC).isoformat(),
        "total_clis": len(versions),
        "drifted": len(drifted),
        "probes": probed,
    }
    REPORT_FILE.write_text(json.dumps(report_data, indent=2, ensure_ascii=False))
    print(f"📄 Report: {REPORT_FILE}")

    # Summary
    if not drifted:
        print(f"✅ All {len(versions)} CLIs up to date")
    else:
        print(f"⚠️ {len(drifted)} CLI(s) have updates available")
        _bark_notify(drifted, probed)


def _bark_notify(drifted: list, probed: list) -> None:
    """Bark push notification for drifted CLIs."""
    bark_url = os.environ.get("BARK_URL", "")
    if not bark_url:
        return
    try:
        title = f"CLI Drift: {len(drifted)} update(s)"
        body = ", ".join(f"{v.cli_name} {v.installed}→{v.remote}" for v in drifted)
        url = f"{bark_url}/{title}/{body}?group=workshop"
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
