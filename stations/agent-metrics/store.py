"""NgRx-style FeatureStore for Agent Metrics — usage aggregation + session tracking.

Provides a reducer/selector facade over the session_store module's in-memory
state. Stations don't import from core's src.shared.*, so we add core/ to
sys.path here.

State shape:
    {
        "active_sessions": {
            "<session_key>": {
                "id": str,
                "sid": str,
                "cli": str,
                "model_id": str,
                "model_display": str,
                "project": str,
                "cost_usd": float,
                "input_tokens": int,
                "output_tokens": int,
                "context_used_pct": float,
                "first_seen": str,          # ISO timestamp
                "last_seen": str,           # ISO timestamp
                "is_active": bool,
            }
        },
        "daily_usage": {
            "input_tokens": int,
            "output_tokens": int,
            "cost_usd": float,
            "session_count": int,
            "date": str,                    # YYYY-MM-DD
        },
        "quota_remaining": None | dict,     # provider → remaining quota
    }
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Path bootstrap — stations don't inherit core's Python path ──
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── Actions ──────────────────────────────────────────────────────────────────

SessionStarted = create_action("metrics.session.started")
# payload: {"session_key": str, "id": str, "sid": str, "cli": str, "first_seen": str}

SessionEnded = create_action("metrics.session.ended")
# payload: {"session_key": str}

TokensUsed = create_action("metrics.tokens.used")
# payload: {
#     "session_key": str, "cost_usd": float,
#     "input_tokens": int, "output_tokens": int,
#     "context_used_pct": float, "model_id": str, "model_display": str,
#     "project": str, "last_seen": str,
# }

QuotaChecked = create_action("metrics.quota.checked")
# payload: {"quota": dict}  — provider → remaining value

DailyRollover = create_action("metrics.daily.rollover")
# payload: {"date": str}  — new date (YYYY-MM-DD)

SessionExpired = create_action("metrics.session.expired")
# payload: {"session_key": str}

# ── Reducer helpers ───────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _handle_session_started(state, action) -> object:
    p = action.payload or {}
    key = p.get("session_key", "")
    if not key:
        return state

    sessions = state["active_sessions"]
    # Don't overwrite existing sessions
    if hasattr(sessions, "get") and sessions.get(key) is not None:
        return state

    entry = {
        "id": p.get("id", key),
        "sid": p.get("sid", ""),
        "cli": p.get("cli", "claude"),
        "model_id": "",
        "model_display": "",
        "project": "",
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "context_used_pct": 0.0,
        "first_seen": p.get("first_seen", datetime.now(UTC).isoformat()),
        "last_seen": p.get("first_seen", datetime.now(UTC).isoformat()),
        "is_active": True,
    }
    new_sessions = sessions.set(key, to_immutable(entry))

    daily = state["daily_usage"]
    new_daily = daily.set("session_count", daily["session_count"] + 1)

    return state.set("active_sessions", new_sessions).set("daily_usage", new_daily)


def _handle_session_ended(state, action) -> object:
    p = action.payload or {}
    key = p.get("session_key", "")

    sessions = state["active_sessions"]
    if not hasattr(sessions, "get") or sessions.get(key) is None:
        return state

    # Mark inactive rather than delete (preserves last cost snapshot)
    entry = sessions.get(key)
    entry_dict = dict(entry) if isinstance(entry, dict) else {k: v for k, v in entry.items()}
    entry_dict["is_active"] = False
    new_sessions = sessions.set(key, to_immutable(entry_dict))
    return state.set("active_sessions", new_sessions)


def _handle_tokens_used(state, action) -> object:
    p = action.payload or {}
    key = p.get("session_key", "")
    cost_new = float(p.get("cost_usd", 0.0))
    input_tokens = int(p.get("input_tokens", 0))
    output_tokens = int(p.get("output_tokens", 0))

    sessions = state["active_sessions"]
    entry = sessions.get(key) if hasattr(sessions, "get") else None

    # Delta cost — subtract old cost before adding new cost to daily total
    old_cost = 0.0
    if entry is not None:
        old_cost = float(entry["cost_usd"]) if hasattr(entry, "__getitem__") else 0.0

    # Update session entry
    if entry is not None:
        entry_dict = dict(entry) if isinstance(entry, dict) else {k: v for k, v in entry.items()}
    else:
        entry_dict = {
            "id": key,
            "sid": "",
            "cli": "claude",
            "model_id": "",
            "model_display": "",
            "project": "",
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "context_used_pct": 0.0,
            "first_seen": datetime.now(UTC).isoformat(),
            "last_seen": datetime.now(UTC).isoformat(),
            "is_active": True,
        }

    entry_dict["cost_usd"] = cost_new
    entry_dict["input_tokens"] = input_tokens
    entry_dict["output_tokens"] = output_tokens
    entry_dict["context_used_pct"] = float(p.get("context_used_pct", 0.0))
    entry_dict["model_id"] = p.get("model_id", entry_dict.get("model_id", ""))
    entry_dict["model_display"] = p.get("model_display", entry_dict.get("model_display", ""))
    entry_dict["project"] = p.get("project", entry_dict.get("project", ""))
    entry_dict["last_seen"] = p.get("last_seen", datetime.now(UTC).isoformat())
    entry_dict["is_active"] = True

    new_sessions = sessions.set(key, to_immutable(entry_dict))

    # Accumulate daily_usage with delta cost
    daily = state["daily_usage"]
    cost_delta = round(cost_new - old_cost, 6)
    new_cost = round(float(daily["cost_usd"]) + cost_delta, 6)

    # Accumulate tokens — we track cumulative totals for active sessions
    # Note: input/output_tokens in payload are per-session total (not delta),
    # so we compute the difference against the old session value.
    old_in = (
        int(entry["input_tokens"]) if entry is not None and hasattr(entry, "__getitem__") else 0
    )
    old_out = (
        int(entry["output_tokens"]) if entry is not None and hasattr(entry, "__getitem__") else 0
    )
    in_delta = input_tokens - old_in
    out_delta = output_tokens - old_out

    new_daily = daily.set("cost_usd", new_cost)
    new_daily = new_daily.set("input_tokens", int(daily["input_tokens"]) + in_delta)
    new_daily = new_daily.set("output_tokens", int(daily["output_tokens"]) + out_delta)

    return state.set("active_sessions", new_sessions).set("daily_usage", new_daily)


def _handle_quota_checked(state, action) -> object:
    p = action.payload or {}
    quota = p.get("quota", {})
    return state.set("quota_remaining", to_immutable(quota))


def _handle_daily_rollover(state, action) -> object:
    p = action.payload or {}
    new_date = p.get("date", _today())

    # Reset daily counters for the new day
    new_daily = to_immutable(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "session_count": 0,
            "date": new_date,
        }
    )

    # Clear all sessions on rollover
    return state.set("daily_usage", new_daily).set("active_sessions", to_immutable({}))


def _handle_session_expired(state, action) -> object:
    p = action.payload or {}
    key = p.get("session_key", "")

    sessions = state["active_sessions"]
    if not hasattr(sessions, "get") or sessions.get(key) is None:
        return state

    entry = sessions.get(key)
    entry_dict = dict(entry) if isinstance(entry, dict) else {k: v for k, v in entry.items()}
    entry_dict["is_active"] = False
    new_sessions = sessions.set(key, to_immutable(entry_dict))
    return state.set("active_sessions", new_sessions)


# ── Reducer ───────────────────────────────────────────────────────────────────

metrics_reducer = create_reducer(
    {
        "active_sessions": {},
        "daily_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "session_count": 0,
            "date": "",
        },
        "quota_remaining": None,
    },
    on(SessionStarted, _handle_session_started),
    on(SessionEnded, _handle_session_ended),
    on(TokensUsed, _handle_tokens_used),
    on(QuotaChecked, _handle_quota_checked),
    on(DailyRollover, _handle_daily_rollover),
    on(SessionExpired, _handle_session_expired),
)

# ── Selectors ─────────────────────────────────────────────────────────────────

select_daily_usage = create_selector(lambda s: s["daily_usage"])

select_active_sessions = create_selector(
    lambda s: s["active_sessions"],
    result_fn=lambda sessions: {
        k: v
        for k, v in (sessions.items() if hasattr(sessions, "items") else {}.items())
        if (v.get("is_active") if isinstance(v, dict) else v["is_active"])
    },
)

select_session_count = create_selector(
    lambda s: s["active_sessions"],
    result_fn=lambda sessions: sum(
        1
        for v in (sessions.values() if hasattr(sessions, "values") else [])
        if (v.get("is_active") if isinstance(v, dict) else v["is_active"])
    ),
)

select_quota_remaining = create_selector(lambda s: s["quota_remaining"])

select_daily_cost = create_selector(
    lambda s: s["daily_usage"],
    result_fn=lambda daily: float(daily["cost_usd"]) if hasattr(daily, "__getitem__") else 0.0,
)

select_total_tokens_today = create_selector(
    lambda s: s["daily_usage"],
    result_fn=lambda daily: (
        int(daily["input_tokens"]) + int(daily["output_tokens"])
        if hasattr(daily, "__getitem__")
        else 0
    ),
)

# ── Store instance ────────────────────────────────────────────────────────────

metrics_store = FeatureStore(
    "agent-metrics",
    metrics_reducer,
)
