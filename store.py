"""Hook Observatory — FeatureStore (SELECTOR depth).

Tracks hook event ingestion, handler execution stats, and failure rate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── Actions ──────────────────────────────────────────────────────────────────

HookEventReceived = create_action("hooks.event.received")
HandlerExecuted = create_action("hooks.handler.executed")
HandlerFailed = create_action("hooks.handler.failed")
SpoolDrained = create_action("hooks.spool.drained")

# ── Reducer ──────────────────────────────────────────────────────────────────

_MAX_FAILURES = 50


def _on_handler_executed(s, a):
    """Increment success count for the handler named in payload.get('handler')."""
    handler = (a.payload or {}).get("handler", "unknown")
    stats = s["handler_stats"]
    current = stats.get(handler, to_immutable({"success": 0, "failed": 0}))
    updated_entry = current.set("success", current["success"] + 1)
    new_stats = stats.set(handler, updated_entry)
    return s.set("handler_stats", new_stats)


def _on_handler_failed(s, a):
    """Append failure record to recent_failures (capped at 50)."""
    handler = (a.payload or {}).get("handler", "unknown")
    stats = s["handler_stats"]
    current = stats.get(handler, to_immutable({"success": 0, "failed": 0}))
    updated_entry = current.set("failed", current["failed"] + 1)
    new_stats = stats.set(handler, updated_entry)

    failures = list(s["recent_failures"])
    failures.append(to_immutable(a.payload or {}))
    if len(failures) > _MAX_FAILURES:
        failures = failures[-_MAX_FAILURES:]

    return batch_update(
        s,
        {
            "handler_stats": new_stats,
            "recent_failures": tuple(failures),
        },
    )


hooks_reducer = create_reducer(
    {"event_count": 0, "handler_stats": {}, "recent_failures": []},
    on(HookEventReceived, lambda s, a: s.set("event_count", s["event_count"] + 1)),
    on(HandlerExecuted, _on_handler_executed),
    on(HandlerFailed, _on_handler_failed),
    on(SpoolDrained, lambda s, a: s),  # no-op — used for side-effects only
)

# ── Selectors ─────────────────────────────────────────────────────────────────

select_handler_stats = create_selector(lambda s: s["handler_stats"])

select_failure_rate = create_selector(
    lambda s: s["event_count"],
    lambda s: s["recent_failures"],
    result_fn=lambda ec, rf: len(rf) / max(ec, 1),
)

select_event_count = create_selector(lambda s: s["event_count"])
select_recent_failures = create_selector(lambda s: s["recent_failures"])

# ── Store ─────────────────────────────────────────────────────────────────────

hook_store = FeatureStore("hook-observatory", hooks_reducer)
