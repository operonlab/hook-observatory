"""System Monitor — FeatureStore (SELECTOR depth).

Tracks hardware metrics samples, active alerts, and CPU pressure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── Actions ──────────────────────────────────────────────────────────────────

MetricsSampled = create_action("sysmon.metrics.sampled")
AlertTriggered = create_action("sysmon.alert.triggered")
AlertResolved = create_action("sysmon.alert.resolved")

# ── Reducer ──────────────────────────────────────────────────────────────────

sysmon_reducer = create_reducer(
    {"latest_metrics": {}, "active_alerts": {}, "sample_count": 0},
    on(
        MetricsSampled,
        lambda s, a: batch_update(
            s,
            {
                "latest_metrics": a.payload or {},
                "sample_count": s["sample_count"] + 1,
            },
        ),
    ),
    on(
        AlertTriggered,
        lambda s, a: update_in(
            s,
            ["active_alerts", (a.payload or {}).get("alert_id", "")],
            lambda _: a.payload or {},
        ),
    ),
    on(
        AlertResolved,
        lambda s, a: update_in(
            s,
            ["active_alerts"],
            lambda alerts: to_immutable(
                {
                    k: v
                    for k, v in (alerts or {}).items()
                    if k != (a.payload or {}).get("alert_id", "")
                }
            ),
        ),
    ),
)

# ── Selectors ─────────────────────────────────────────────────────────────────

select_latest_metrics = create_selector(lambda s: s["latest_metrics"])
select_active_alerts = create_selector(lambda s: s["active_alerts"])
select_sample_count = create_selector(lambda s: s["sample_count"])

select_cpu_pressure = create_selector(
    lambda s: s["latest_metrics"],
    result_fn=lambda m: (m or {}).get("cpu_percent", 0),
)

select_has_active_alerts = create_selector(
    lambda s: s["active_alerts"],
    result_fn=lambda alerts: len(alerts) > 0,
)

# ── Store ─────────────────────────────────────────────────────────────────────

sysmon_store = FeatureStore("system-monitor", sysmon_reducer)
