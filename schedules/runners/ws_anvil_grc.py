#!/usr/bin/env python3
"""
ws_anvil_grc.py — Daily skill success rate reflection (Anvil G-R-C)

Directly imports AnvilGRCAdapter from the anvil station, connects to
the anvil PostgreSQL schema, and runs a 30-day reflect pass.

Logs: ~/workshop/outputs/anvil/logs/grc.log
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Add anvil src/ to path so we can import grc_adapter and its deps.
ANVIL_SRC = Path(__file__).resolve().parents[2] / "stations" / "anvil" / "src"
CORE_SRC = Path(__file__).resolve().parents[2] / "core" / "src"
sys.path.insert(0, str(ANVIL_SRC))
sys.path.insert(0, str(CORE_SRC))

# ── Configuration ─────────────────────────────────────────────────────────────
LOG_DIR = Path.home() / "workshop" / "outputs" / "anvil" / "logs"
LOG_FILE = LOG_DIR / "grc.log"
DATABASE_URL = "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop"
SCOPE_ID = "global"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[anvil-grc] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


async def run() -> None:
    from grc_adapter import AnvilGRCAdapter  # type: ignore[import]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        adapter = AnvilGRCAdapter()

        async with session_factory() as db:
            blocks = await adapter.fetch_blocks(db, scope_id=SCOPE_ID)
            log(f"fetched {len(blocks)} invocations (last 30d)")

        items = adapter.gather_items(SCOPE_ID, blocks=blocks)
        result = adapter.reflect(items, scope_id=SCOPE_ID)

        log(f"items_analyzed={result.items_analyzed}")

        for insight in result.insights:
            log(f"insight: {insight}")

        for anomaly in result.anomalies:
            log(f"ANOMALY: {anomaly}")

        # Emit key metrics as JSON line for downstream consumers
        summary = {
            "reflected_at": result.reflected_at.isoformat(),
            "items_analyzed": result.items_analyzed,
            "total_invocations": result.metrics.get("total_invocations", 0),
            "overall_success_rate": result.metrics.get("overall_success_rate", 0),
            "degrading_skill_count": result.metrics.get("degrading_skill_count", 0),
            "anomaly_count": len(result.anomalies),
        }
        log(f"summary: {json.dumps(summary)}")

        # ── Refresh utility scores (Memento-Skills pattern) ───────────────
        try:
            from services.telemetry import TelemetryService

            async with session_factory() as session:
                svc = TelemetryService(session)
                utility_count = await svc.refresh_all_utilities()
                await session.commit()
            log(f"Refreshed utility scores for {utility_count} skills")
        except Exception as exc:
            log(f"Utility refresh failed: {exc}")

    finally:
        await engine.dispose()


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Anvil GRC reflect started ==========")

    asyncio.run(run())

    log("========== Anvil GRC reflect complete ==========")


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"  # noqa: S108
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()
