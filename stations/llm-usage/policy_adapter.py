#!/usr/bin/env python3
"""
Model Policy Adapter — bridge between llm-usage station and model-policy.py.

Provides a unified data interface so model-policy can read CC usage from
the llm-usage station API or latest.json, instead of fetching sysmon directly.

Usage as library:
    from policy_adapter import PolicyDataProvider
    provider = PolicyDataProvider()
    usage = provider.get_cc_usage()
    recommendation = provider.get_mode_recommendation()

Usage as CLI:
    python3 policy_adapter.py usage           # CC 5h/7d usage
    python3 policy_adapter.py recommend       # Mode recommendation
    python3 policy_adapter.py full            # Full policy data
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def _resolve_path(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p)))


def _load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


class PolicyDataProvider:
    """Provides usage data in model-policy.py compatible format.

    Data source priority:
    1. llm-usage station API (http://localhost:9525/subscription)
    2. latest.json on disk
    3. Sysmon API direct (fallback — same as V1 model-policy)
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or _load_config()
        server = self.config.get("server", {})
        self.api_url = f"http://{server.get('host', '127.0.0.1')}:{server.get('port', 9525)}"
        coll = self.config.get("collection", {})
        self.latest_file = _resolve_path(
            coll.get("latest_file", "~/.claude/data/llm-usage/latest.json")
        )
        mp = self.config.get("model_policy", {})
        self.sysmon_url = mp.get("sysmon_url", "")
        self.state_path = _resolve_path(
            mp.get("state_path", "~/.claude/data/model-policy/state.json")
        )
        self.config_path = _resolve_path(
            mp.get("config_path", "~/.claude/data/model-policy/config.json")
        )

    def get_cc_usage(self) -> dict:
        """Return CC 5h/7d usage in model-policy compatible format.

        Returns:
            {
                "cc_5h_pct": int | None,
                "cc_7d_pct": int | None,
                "source": str,  # "station_api" | "latest_json" | "sysmon" | "unavailable"
            }
        """
        # Source 1: Station API
        data = self._try_station_api()
        if data:
            return data

        # Source 2: latest.json
        data = self._try_latest_json()
        if data:
            return data

        # Source 3: Sysmon direct (V1 fallback)
        data = self._try_sysmon()
        if data:
            return data

        return {"cc_5h_pct": None, "cc_7d_pct": None, "source": "unavailable"}

    def get_mode_recommendation(self) -> str:
        """Recommend boost/normal mode based on current usage.

        Uses the same threshold logic as model-policy.py:
        - BOOST if cc_5h < 25% AND cc_7d < 40%
        - NORMAL if cc_5h > 50% OR cc_7d > 60%
        - Otherwise: keep current mode (hysteresis)
        """
        usage = self.get_cc_usage()
        cc_5h = usage.get("cc_5h_pct")
        cc_7d = usage.get("cc_7d_pct")

        if cc_5h is None or cc_7d is None:
            return self._current_mode()

        # Load thresholds from model-policy config
        thresholds = self._load_thresholds()
        boost_t = thresholds.get("boost", {})
        normal_t = thresholds.get("normal", {})

        is_boost = (
            cc_5h < boost_t.get("cc_5h_below", 25)
            and cc_7d < boost_t.get("cc_7d_below", 40)
        )
        is_normal = (
            cc_5h > normal_t.get("cc_5h_above", 50)
            or cc_7d > normal_t.get("cc_7d_above", 60)
        )

        if is_boost:
            return "boost"
        if is_normal:
            return "normal"
        return self._current_mode()

    def get_full_policy_data(self) -> dict:
        """Return complete policy-relevant data."""
        usage = self.get_cc_usage()
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "cc_usage": usage,
            "current_mode": self._current_mode(),
            "recommended_mode": self.get_mode_recommendation(),
            "api_budget": self._get_api_budget_status(),
        }

    # --- Internal data sources ---

    def _try_station_api(self) -> dict | None:
        """Fetch CC usage from llm-usage station API."""
        try:
            req = urllib.request.Request(
                f"{self.api_url}/subscription",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())

            cc = self._extract_cc_from_subscription(data)
            if cc:
                cc["source"] = "station_api"
                return cc
        except Exception:
            pass
        return None

    def _try_latest_json(self) -> dict | None:
        """Read CC usage from latest.json on disk."""
        if not self.latest_file.exists():
            return None
        try:
            with open(self.latest_file) as f:
                snapshot = json.load(f)
            sub = snapshot.get("subscription", {})
            cc = self._extract_cc_from_subscription(sub)
            if cc:
                cc["source"] = "latest_json"
                return cc
        except Exception:
            pass
        return None

    def _try_sysmon(self) -> dict | None:
        """Fetch CC usage from sysmon API (V1 fallback)."""
        if not self.sysmon_url:
            return None
        try:
            req = urllib.request.Request(
                self.sysmon_url, headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            cc_5h = self._parse_pct(data.get("llm_cc_5h", "?"))
            cc_7d = self._parse_pct(data.get("llm_cc_7d", "?"))
            if cc_5h is not None:
                return {"cc_5h_pct": cc_5h, "cc_7d_pct": cc_7d, "source": "sysmon"}
        except Exception:
            pass
        return None

    def _extract_cc_from_subscription(self, sub_data: dict) -> dict | None:
        """Extract CC usage from subscription collector output."""
        providers = sub_data.get("providers", [])
        for p in providers:
            if p.get("cli") == "claude-code":
                cc_5h = p.get("quota_5h_pct")
                cc_7d = p.get("quota_7d_pct")
                if cc_5h is not None:
                    return {"cc_5h_pct": cc_5h, "cc_7d_pct": cc_7d}
        return None

    def _current_mode(self) -> str:
        """Read current mode from model-policy state.json."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f).get("mode", "normal")
            except Exception:
                pass
        return "normal"

    def _load_thresholds(self) -> dict:
        """Load threshold config from model-policy config.json."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return json.load(f).get("thresholds", {})
            except Exception:
                pass
        # Defaults matching model-policy.py
        return {
            "boost": {"cc_5h_below": 25, "cc_7d_below": 40},
            "normal": {"cc_5h_above": 50, "cc_7d_above": 60},
        }

    def _get_api_budget_status(self) -> dict:
        """Get API budget status from latest snapshot."""
        if self.latest_file.exists():
            try:
                with open(self.latest_file) as f:
                    snapshot = json.load(f)
                mtd = snapshot.get("api", {}).get("month_to_date", {})
                return {
                    "used_usd": mtd.get("total_cost_usd", 0),
                    "budget_usd": mtd.get("budget_usd", 0),
                    "used_pct": mtd.get("budget_used_pct", 0),
                }
            except Exception:
                pass
        return {"used_usd": 0, "budget_usd": 0, "used_pct": 0}

    @staticmethod
    def _parse_pct(val) -> int | None:
        if isinstance(val, str) and val.endswith("%"):
            try:
                return int(val.rstrip("%"))
            except ValueError:
                pass
        if isinstance(val, (int, float)):
            return int(val)
        return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Model Policy Adapter")
    parser.add_argument(
        "command",
        choices=["usage", "recommend", "full"],
        help="Data command",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    parser.add_argument("--compact", action="store_true", help="Compact JSON")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = _load_config(config_path)
    provider = PolicyDataProvider(config)

    if args.command == "usage":
        result = provider.get_cc_usage()
    elif args.command == "recommend":
        result = {"mode": provider.get_mode_recommendation()}
    elif args.command == "full":
        result = provider.get_full_policy_data()
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
