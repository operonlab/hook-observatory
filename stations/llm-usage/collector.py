#!/usr/bin/env python3
"""
Unified Collector — integrates subscription + API data collection.

Replaces V1 server.js (Node.js → Python).
Writes snapshots to ~/.claude/data/llm-usage/snapshots/{timestamp}.json
and maintains ~/.claude/data/llm-usage/latest.json.

Usage:
    python3 collector.py                # Full collection
    python3 collector.py --sub-only     # Subscription only
    python3 collector.py --api-only     # API only
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _resolve_path(p: str) -> Path:
    """Expand ~ and env vars in path strings."""
    return Path(os.path.expanduser(os.path.expandvars(p)))


class UnifiedCollector:
    """Orchestrates subscription + API collection into unified snapshots."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or load_config()
        coll = self.config.get("collection", {})
        self.snapshot_dir = _resolve_path(
            coll.get("snapshot_dir", "~/.claude/data/llm-usage/snapshots")
        )
        self.latest_file = _resolve_path(
            coll.get("latest_file", "~/.claude/data/llm-usage/latest.json")
        )
        self.retention_days = coll.get("retention_days", 90)

    def collect_all(self) -> dict:
        """Run full dual-track collection, write snapshot + latest."""
        ts = datetime.now(UTC)
        sub_data = self.collect_subscription()
        api_data = self.collect_api()

        sub_total = sub_data.get("total_monthly_cost_usd", 0)
        api_total = api_data.get("month_to_date", {}).get("total_cost_usd", 0)
        combined_total = round(sub_total + api_total, 2)

        snapshot = {
            "timestamp": ts.isoformat(),
            "subscription": sub_data,
            "api": api_data,
            "combined": {
                "total_monthly_cost_usd": combined_total,
                "subscription_portion_usd": sub_total,
                "api_portion_usd": api_total,
            },
        }

        self._write_snapshot(snapshot, ts)
        self._write_latest(snapshot)
        self._cleanup_old_snapshots()

        return snapshot

    def collect_subscription(self) -> dict:
        """Delegate to subscription_collector."""
        from subscription_collector import collect_all as collect_subs

        return collect_subs(self.config)

    def collect_api(self) -> dict:
        """Delegate to api_collector."""
        from api_collector import collect_api_usage

        return collect_api_usage(self.config, days=30)

    def _write_snapshot(self, data: dict, ts: datetime) -> Path:
        """Write timestamped snapshot file."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        filename = ts.strftime("%Y%m%dT%H%M%SZ") + ".json"
        path = self.snapshot_dir / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"Snapshot saved: {path}", file=sys.stderr)
        return path

    def _write_latest(self, data: dict) -> None:
        """Overwrite latest.json with current snapshot."""
        self.latest_file.parent.mkdir(parents=True, exist_ok=True)
        self.latest_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"Latest updated: {self.latest_file}", file=sys.stderr)

    def _cleanup_old_snapshots(self) -> None:
        """Remove snapshots older than retention_days."""
        if not self.snapshot_dir.exists():
            return
        cutoff = time.time() - (self.retention_days * 86400)
        removed = 0
        for f in self.snapshot_dir.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        if removed:
            print(f"Cleaned up {removed} old snapshot(s)", file=sys.stderr)

    def read_latest(self) -> dict | None:
        """Read the latest snapshot from disk."""
        if self.latest_file.exists():
            with open(self.latest_file) as f:
                return json.load(f)
        return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Unified LLM Usage Collector")
    parser.add_argument(
        "--sub-only", action="store_true",
        help="Collect subscription data only",
    )
    parser.add_argument(
        "--api-only", action="store_true",
        help="Collect API data only",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    parser.add_argument("--compact", action="store_true", help="Compact JSON")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = load_config(config_path)
    collector = UnifiedCollector(config)

    if args.sub_only:
        result = collector.collect_subscription()
    elif args.api_only:
        result = collector.collect_api()
    else:
        result = collector.collect_all()

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
