"""Model Policy Adapter — bridge between agent-metrics and model-policy.py.

Provides unified data interface so model-policy can read CC usage from
the agent-metrics API or latest.json, instead of fetching sysmon directly.

Ported from llm-usage station's policy_adapter.py.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from agent_metrics.config import settings


def _resolve_path(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p)))


class PolicyDataProvider:
    """Provides usage data in model-policy.py compatible format.

    Data source priority:
    1. agent-metrics station API (http://127.0.0.1:8795/usage/subscription)
    2. latest.json on disk
    3. Sysmon API direct (fallback)
    """

    def __init__(self) -> None:
        self.api_url = f"http://{settings.HOST}:{settings.PORT}"
        self.latest_file = _resolve_path(settings.COLLECTION_LATEST_FILE)
        self.sysmon_url = settings.SYSMON_URL
        self.state_path = _resolve_path(settings.MODEL_POLICY_STATE_PATH)
        self.config_path = _resolve_path(settings.MODEL_POLICY_CONFIG_PATH)

    def get_cc_usage(self) -> dict:
        """Return CC 5h/7d usage in model-policy compatible format."""
        data = self._try_station_api()
        if data:
            return data
        data = self._try_latest_json()
        if data:
            return data
        data = self._try_sysmon()
        if data:
            return data
        return {"cc_5h_pct": None, "cc_7d_pct": None, "source": "unavailable"}

    def get_mode_recommendation(self) -> str:
        """Recommend boost/normal mode based on current usage."""
        usage = self.get_cc_usage()
        cc_5h = usage.get("cc_5h_pct")
        cc_7d = usage.get("cc_7d_pct")
        if cc_5h is None or cc_7d is None:
            return self._current_mode()

        thresholds = self._load_thresholds()
        boost_t = thresholds.get("boost", {})
        normal_t = thresholds.get("normal", {})

        is_boost = cc_5h < boost_t.get("cc_5h_below", 25) and cc_7d < boost_t.get(
            "cc_7d_below", 40
        )
        is_normal = cc_5h > normal_t.get("cc_5h_above", 50) or cc_7d > normal_t.get(
            "cc_7d_above", 60
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
        """Fetch CC usage from agent-metrics /usage/subscription endpoint."""
        try:
            req = urllib.request.Request(
                f"{self.api_url}/usage/subscription",
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
                self.sysmon_url,
                headers={"Accept": "application/json"},
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

    @staticmethod
    def _extract_cc_from_subscription(sub_data: dict) -> dict | None:
        providers = sub_data.get("providers", [])
        for p in providers:
            if p.get("cli") == "claude-code":
                cc_5h = p.get("quota_5h_pct")
                cc_7d = p.get("quota_7d_pct")
                if cc_5h is not None:
                    return {"cc_5h_pct": cc_5h, "cc_7d_pct": cc_7d}
        return None

    def _current_mode(self) -> str:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f).get("mode", "normal")
            except Exception:
                pass
        return "normal"

    def _load_thresholds(self) -> dict:
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return json.load(f).get("thresholds", {})
            except Exception:
                pass
        return {
            "boost": {"cc_5h_below": 25, "cc_7d_below": 40},
            "normal": {"cc_5h_above": 50, "cc_7d_above": 60},
        }

    def _get_api_budget_status(self) -> dict:
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
    def _parse_pct(val: str | int | float) -> int | None:
        if isinstance(val, str) and val.endswith("%"):
            try:
                return int(val.rstrip("%"))
            except ValueError:
                pass
        if isinstance(val, (int, float)):
            return int(val)
        return None
