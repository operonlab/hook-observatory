#!/usr/bin/env python3
"""
tmux_status.py — Unified tmux status bar data provider.

Replaces: sysmon-read.sh, quota-all.sh, quota-ex-segment.sh

Usage:
    python3 tmux_status.py <metric>

Metrics:
    System:  cpu, mem, net, disk, cc, pressure
    Quota:   cc-5h, cc-7d, cc-ex, cx-5h, cx-7d, gm-pro, gm-flash
    Special: ex-segment (styled EX powerline segment)

Read order:
    1. /tmp/agent-metrics-sysmon.json (primary, 5s cache)
    2. HTTP API agent-metrics (fallback)
    3. "?" (graceful fallback)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PRIMARY = Path("/tmp/agent-metrics-sysmon.json")

# Metric → JSON field mapping
FIELD_MAP = {
    # System metrics (from sysmon-read.sh)
    "cpu": "cpu_display",
    "mem": "mem_display",
    "net": "net_display",
    "disk": "disk_display",
    "cc": "cc_display",
    "pressure": "mem_pressure",
    # LLM quota metrics (from quota-all.sh)
    "cc-5h": "llm_cc_5h",
    "cc-7d": "llm_cc_7d",
    "cc-ex": "llm_cc_ex",
    "cx-5h": "llm_cx_5h",
    "cx-7d": "llm_cx_7d",
    "gm-pro": "llm_gm_pro",
    "gm-flash": "llm_gm_flash",
}

# Quota metrics use different API endpoint and staleness threshold
QUOTA_METRICS = {"cc-5h", "cc-7d", "cc-ex", "cx-5h", "cx-7d", "gm-pro", "gm-flash"}


def _file_age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return 9999


def _read_from_file(field: str, max_age: float) -> str | None:
    if not PRIMARY.exists():
        return None
    if _file_age(PRIMARY) > max_age:
        return None
    try:
        data = json.loads(PRIMARY.read_text())
        val = data.get(field)
        if val is not None and str(val) not in ("None", ""):
            return str(val)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _read_from_api(metric: str, field: str) -> str | None:
    if metric in QUOTA_METRICS:
        url = "http://127.0.0.1:8795/quota/formatted"
        key = metric
    else:
        url = "http://127.0.0.1:8795/sysmon/current"
        key = field
    try:
        with urlopen(url, timeout=1) as resp:
            data = json.loads(resp.read())
            val = data.get(key)
            if val is not None and str(val) not in ("None", ""):
                return str(val)
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def _tmux_var(name: str) -> str:
    try:
        r = subprocess.run(
            ["tmux", "show", "-gqv", name],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def get_metric(metric: str) -> str:
    field = FIELD_MAP.get(metric)
    if not field:
        return "?"

    max_age = 120.0 if metric in QUOTA_METRICS else 15.0

    val = _read_from_file(field, max_age)
    if val:
        return val

    val = _read_from_api(metric, field)
    if val:
        return val

    return "?"


def ex_segment() -> str:
    """Conditional EX powerline segment with Catppuccin colors."""
    val = get_metric("cc-ex")
    if not val or val == "?":
        return ""

    flamingo = _tmux_var("@thm_flamingo")
    crust = _tmux_var("@thm_crust")
    fg = _tmux_var("@thm_fg")
    s0 = _tmux_var("@thm_surface_0")
    mantle = _tmux_var("@thm_mantle")

    return (
        f"#[fg={flamingo},bg={mantle}]"
        f"#[fg={crust},bg={flamingo}] EX "
        f"#[fg={fg},bg={s0}] {val} "
        f"#[fg={s0},bg={mantle}]"
    )


def main():
    metric = sys.argv[1] if len(sys.argv) > 1 else "cpu"

    if metric == "ex-segment":
        print(ex_segment(), end="")
    else:
        print(get_metric(metric), end="")


if __name__ == "__main__":
    main()
