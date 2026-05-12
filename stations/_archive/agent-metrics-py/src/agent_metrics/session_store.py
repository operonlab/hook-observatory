"""In-memory session store — async-safe, ported from V1.

This is the single source of truth for active sessions during runtime.
Periodically flushed to DB by the aggregator.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from .config import settings
from .models import IngestRequest

log = structlog.get_logger()

_lock = asyncio.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_daily_cost: float = 0.0
_current_date: str = ""


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _round4(n: float) -> float:
    return round(n * 10000) / 10000


def _is_stale(session: dict) -> bool:
    return (time.time() - session["last_seen_ts"]) > settings.SESSION_EXPIRY_SECONDS


async def ingest(req: IngestRequest) -> dict[str, Any]:
    """Process an ingest request. Returns {total, sessions, daily}."""
    global _daily_cost, _current_date

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    now_ts = time.time()

    async with _lock:
        today = _today()

        # Daily rollover
        if _current_date != today:
            _current_date = today
            _daily_cost = 0.0
            for s in _sessions.values():
                s["is_active"] = False
            _sessions.clear()

        # Session key — prefer full session_id, fall back to sid
        key = req.session_id if req.session_id else req.sid

        # Delta cost calculation
        old_cost = _sessions[key]["cost_usd"] if key in _sessions else 0.0
        _daily_cost = _round4(_daily_cost - old_cost + req.cost)

        # Upsert session
        if key not in _sessions:
            _sessions[key] = {
                "id": req.session_id or uuid.uuid4().hex,
                "sid": req.sid,
                "cli": req.cli or "claude",
                "first_seen": now_iso,
                "is_active": True,
            }

        s = _sessions[key]
        s["cli"] = req.cli or s.get("cli", "claude")
        s["model_id"] = req.model_id or s.get("model_id", "")
        s["model_display"] = req.model_display or s.get("model_display", "")
        s["project"] = req.project or s.get("project", "")
        s["cost_usd"] = req.cost
        s["context_used_pct"] = req.context.used_pct
        s["context_window_size"] = req.context.window_size
        s["input_tokens"] = req.context.input_tokens
        s["output_tokens"] = req.context.output_tokens
        s["cache_creation_tokens"] = req.context.cache_creation_tokens
        s["cache_read_tokens"] = req.context.cache_read_tokens
        s["last_seen"] = now_iso
        s["last_seen_ts"] = now_ts
        s["is_active"] = True

        # Aggregate non-stale sessions
        total = 0.0
        count = 0
        for sess in _sessions.values():
            if _is_stale(sess):
                continue
            total += sess["cost_usd"]
            count += 1

        return {
            "total": _round4(total),
            "sessions": count,
            "daily": _round4(_daily_cost),
        }


async def get_active_sessions() -> list[dict[str, Any]]:
    """Return all non-stale sessions."""
    async with _lock:
        return [
            {k: v for k, v in s.items() if k != "last_seen_ts"}
            for s in _sessions.values()
            if not _is_stale(s)
        ]


async def get_daily_summary() -> dict[str, Any]:
    """Return current daily state."""
    async with _lock:
        active = [s for s in _sessions.values() if not _is_stale(s)]
        return {
            "date": _current_date or _today(),
            "total_cost_usd": _round4(_daily_cost),
            "active_sessions": len(active),
        }


async def get_snapshot() -> dict[str, Any]:
    """Return full snapshot for caching."""
    summary = await get_daily_summary()
    summary["sessions"] = await get_active_sessions()
    return summary


async def collect_pending_snapshots() -> list[dict[str, Any]]:
    """Collect snapshots of all active sessions for DB flush."""
    async with _lock:
        now_iso = datetime.now(UTC).isoformat()
        snapshots = []
        for s in _sessions.values():
            if _is_stale(s):
                continue
            snapshots.append({
                "id": uuid.uuid4().hex,
                "ts": now_iso,
                "session_id": s["id"],
                "sid": s["sid"],
                "cli": s.get("cli", "claude"),
                "cost_usd": s["cost_usd"],
                "context_used_pct": s["context_used_pct"],
                "input_tokens": s["input_tokens"],
                "output_tokens": s["output_tokens"],
            })
        return snapshots


async def expire_stale_sessions() -> int:
    """Mark stale sessions inactive, return count expired."""
    async with _lock:
        expired = 0
        stale_keys = [k for k, s in _sessions.items() if _is_stale(s)]
        for k in stale_keys:
            _sessions[k]["is_active"] = False
            expired += 1
        # Remove very old entries (>24h) to prevent memory leak
        day_ago = time.time() - 86400
        remove_keys = [k for k, s in _sessions.items() if s["last_seen_ts"] < day_ago]
        for k in remove_keys:
            del _sessions[k]
        return expired


async def get_daily_rollover_data() -> dict[str, Any] | None:
    """If date has changed, return yesterday's summary for DB storage and reset."""
    global _daily_cost, _current_date

    async with _lock:
        today = _today()
        if _current_date and _current_date != today:
            # Build summary for the old date
            all_sessions = list(_sessions.values())
            total_input = sum(s.get("input_tokens", 0) for s in all_sessions)
            total_output = sum(s.get("output_tokens", 0) for s in all_sessions)
            ctx_pcts = [
                s.get("context_used_pct", 0)
                for s in all_sessions
                if s.get("context_used_pct", 0) > 0
            ]
            summary = {
                "id": uuid.uuid4().hex,
                "date": _current_date,
                "total_cost_usd": _round4(_daily_cost),
                "total_sessions": len(all_sessions),
                "peak_concurrent": len([s for s in all_sessions if not _is_stale(s)]),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "avg_context_pct": round(sum(ctx_pcts) / len(ctx_pcts), 1) if ctx_pcts else 0.0,
                "max_context_pct": round(max(ctx_pcts), 1) if ctx_pcts else 0.0,
            }

            # Reset for new day
            _current_date = today
            _daily_cost = 0.0
            _sessions.clear()

            return summary
        return None


def reset_for_testing() -> None:
    """Reset all state — only for tests."""
    global _daily_cost, _current_date, _sessions
    _sessions.clear()
    _daily_cost = 0.0
    _current_date = ""
