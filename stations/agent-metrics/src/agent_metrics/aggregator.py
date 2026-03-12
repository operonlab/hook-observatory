"""Background aggregator — DB flush, session expiry, daily rollover, retention.

Ported from V1 with sync DB calls replaced by asyncpg pool.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import structlog

from .config import settings
from .db import get_pool
from . import session_store

log = structlog.get_logger()

_last_db_flush = 0.0
_last_retention = 0.0
_last_ops_broadcast = 0.0
_last_usage_broadcast = 0.0

# Broadcast intervals (seconds)
_OPS_BROADCAST_INTERVAL = 30.0
_USAGE_BROADCAST_INTERVAL = 60.0


async def aggregator_loop() -> None:
    """Background loop: session expiry, DB flush, daily rollover, retention."""
    global _last_db_flush, _last_retention, _last_ops_broadcast, _last_usage_broadcast

    now = time.time()
    _last_db_flush = now
    _last_retention = now
    _last_ops_broadcast = now
    _last_usage_broadcast = now

    log.info("aggregator_started")

    # Import SSE broadcast here to avoid circular imports at module level
    from agent_metrics.sse import sse_broadcast

    try:
        while True:
            now = time.time()

            # Session expiry (every tick)
            expired = await session_store.expire_stale_sessions()
            if expired > 0:
                log.info("sessions_expired", count=expired)

            # SSE: broadcast sessions every tick (~10s via EXPIRY_CHECK_INTERVAL)
            try:
                snapshot = await session_store.get_snapshot()
                await sse_broadcast("sessions", snapshot)
            except Exception:
                log.debug("sse_sessions_broadcast_failed", exc_info=True)

            # Daily rollover check
            rollover = await session_store.get_daily_rollover_data()
            if rollover:
                await _save_daily_summary(rollover)
                log.info("daily_rollover", date=rollover["date"], cost=rollover["total_cost_usd"])

            # DB flush (every 60s)
            if now - _last_db_flush >= settings.DB_FLUSH_INTERVAL:
                snapshots = await session_store.collect_pending_snapshots()
                if snapshots:
                    await _flush_snapshots(snapshots)
                _last_db_flush = now

            # SSE: broadcast usage every ~60s
            if now - _last_usage_broadcast >= _USAGE_BROADCAST_INTERVAL:
                try:
                    from agent_metrics.usage_collector import get_month_to_date
                    from agent_metrics.config import settings as _settings

                    loop = asyncio.get_running_loop()
                    mtd = await loop.run_in_executor(None, get_month_to_date)
                    budget = _settings.API_MONTHLY_BUDGET_USD
                    used = mtd.get("total_cost_usd", 0)
                    used_pct = round(used / budget * 100, 1) if budget > 0 else 0
                    usage_payload = {
                        "budget_usd": budget,
                        "used_usd": used,
                        "used_pct": used_pct,
                        "remaining_usd": round(budget - used, 2),
                        "warning": used_pct >= _settings.BUDGET_WARNING_PCT,
                        "days_elapsed": mtd.get("days", 0),
                    }
                    await sse_broadcast("usage", usage_payload)
                except Exception:
                    log.debug("sse_usage_broadcast_failed", exc_info=True)
                _last_usage_broadcast = now

            # SSE: broadcast operations (maestro runs) every ~30s
            if now - _last_ops_broadcast >= _OPS_BROADCAST_INTERVAL:
                try:
                    pool = await get_pool()
                    from agent_metrics.engines import maestro as me

                    runs = await me.list_runs(pool, limit=20)
                    await sse_broadcast("operations", {"runs": runs})
                except Exception:
                    log.debug("sse_operations_broadcast_failed", exc_info=True)
                _last_ops_broadcast = now

            # Retention (every 24h)
            if now - _last_retention >= 86400:
                await _run_retention()
                _last_retention = now

            await asyncio.sleep(settings.EXPIRY_CHECK_INTERVAL)

    except asyncio.CancelledError:
        # Flush remaining on shutdown
        snapshots = await session_store.collect_pending_snapshots()
        if snapshots:
            await _flush_snapshots(snapshots)
        log.info("aggregator_stopped")
        raise


async def _flush_snapshots(snapshots: list[dict]) -> None:
    """Batch insert snapshots into DB via asyncpg."""
    try:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.executemany(
                "INSERT INTO snapshots (id, ts, session_id, sid, cli, cost_usd,"
                " context_used_pct, input_tokens, output_tokens)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                [
                    (
                        snap["id"],
                        datetime.fromisoformat(snap["ts"]),
                        snap["session_id"],
                        snap["sid"],
                        snap.get("cli", "claude"),
                        snap["cost_usd"],
                        snap["context_used_pct"],
                        snap["input_tokens"],
                        snap["output_tokens"],
                    )
                    for snap in snapshots
                ],
            )
        log.info("snapshots_flushed", count=len(snapshots))
    except Exception:
        log.exception("snapshot_flush_failed")


async def _save_daily_summary(summary: dict) -> None:
    """Insert or update daily summary."""
    try:
        pool = await get_pool()
        await pool.execute(
            "INSERT INTO daily_summary"
            " (id, date, total_cost_usd, total_sessions, peak_concurrent,"
            "  total_input_tokens, total_output_tokens, avg_context_pct, max_context_pct)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
            " ON CONFLICT (date) DO UPDATE SET"
            "  total_cost_usd = EXCLUDED.total_cost_usd,"
            "  total_sessions = EXCLUDED.total_sessions,"
            "  peak_concurrent = EXCLUDED.peak_concurrent,"
            "  total_input_tokens = EXCLUDED.total_input_tokens,"
            "  total_output_tokens = EXCLUDED.total_output_tokens,"
            "  avg_context_pct = EXCLUDED.avg_context_pct,"
            "  max_context_pct = EXCLUDED.max_context_pct",
            summary["id"],
            datetime.strptime(summary["date"], "%Y-%m-%d").date(),
            summary["total_cost_usd"],
            summary["total_sessions"],
            summary["peak_concurrent"],
            summary["total_input_tokens"],
            summary["total_output_tokens"],
            summary["avg_context_pct"],
            summary["max_context_pct"],
        )
        log.info("daily_summary_saved", date=summary["date"])
    except Exception:
        log.exception("daily_summary_save_failed")


async def _run_retention() -> None:
    """Purge old snapshots and daily summaries."""
    try:
        pool = await get_pool()
        snap_cutoff = datetime.now(UTC) - timedelta(days=settings.RETENTION_SNAPSHOTS_DAYS)
        daily_cutoff = (datetime.now(UTC) - timedelta(days=settings.RETENTION_DAILY_DAYS)).date()

        async with pool.acquire() as con:
            await con.execute("DELETE FROM snapshots WHERE ts < $1", snap_cutoff)
            await con.execute("DELETE FROM daily_summary WHERE date < $1", daily_cutoff)

        log.info(
            "retention_completed",
            snap_cutoff=snap_cutoff.isoformat(),
            daily_cutoff=str(daily_cutoff),
        )
    except Exception:
        log.exception("retention_failed")
