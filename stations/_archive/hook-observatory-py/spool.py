"""Simplified spool processor — dedup_hash is the safety net."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)

DbWriter = Callable[[list[dict]], Coroutine]


def _hash_event(evt: dict) -> str:
    """Content-based dedup hash: SHA256(event_type + ts + data[:200])[:16]."""
    key = f"{evt.get('event_type', '')}-{evt.get('ts', '')}-{str(evt.get('data', ''))[:200]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


_BACKOFF_STEPS = (2, 30, 60, 120)  # seconds: 2s → 30s → 60s → 120s cap


class SpoolDrainer:
    """Simplified spool processor.

    Flow: events.jsonl → atomic rename → batch INSERT (dedup) → delete
    Crash safety: dedup_hash + ON CONFLICT DO NOTHING ensures re-processing
    is always safe. No state machine, no cursor, no archive needed.
    """

    def __init__(
        self,
        spool_dir: Path,
        drain_interval: float = 2.0,
        batch_size: int = 100,
    ):
        self.spool_dir = spool_dir
        self.drain_interval = drain_interval
        self.batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._consecutive_errors: int = 0

    async def start(self, db_writer: DbWriter) -> None:
        """Start drain loop."""
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._drain_loop(db_writer))
        logger.info("SpoolDrainer started (interval=%.1fs)", self.drain_interval)

    async def stop(self) -> None:
        """Cancel the drain loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SpoolDrainer stopped")

    async def _drain_loop(self, db_writer: DbWriter) -> None:
        """Main loop: rotate active spool → process → delete → sleep.

        Uses exponential backoff on consecutive failures: 2s → 30s → 60s → 120s.
        Resets to normal interval after a successful drain cycle.
        """
        while True:
            try:
                # Process any leftover .draining files first (crash recovery)
                for f in sorted(self.spool_dir.glob("*.draining")):
                    await self._process_file(f, db_writer)

                # Rotate active spool file
                spool = self.spool_dir / "events.jsonl"
                if spool.exists() and spool.stat().st_size > 0:
                    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                    draining = self.spool_dir / f"events-{ts}.draining"
                    spool.rename(draining)
                    await self._process_file(draining, db_writer)

                self._consecutive_errors = 0  # reset backoff on success
            except FileNotFoundError:
                pass  # Race with another drain cycle
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Spool drain error")
                self._consecutive_errors += 1
                backoff = _BACKOFF_STEPS[
                    min(self._consecutive_errors - 1, len(_BACKOFF_STEPS) - 1)
                ]
                logger.warning(
                    "Spool drain backoff: %ds (consecutive_errors=%d)",
                    backoff,
                    self._consecutive_errors,
                )
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(self.drain_interval)

    async def _process_file(self, filepath: Path, db_writer: DbWriter) -> None:
        """Read spool file → batch INSERT → delete on success."""
        events: list[dict] = []

        async with aiofiles.open(filepath) as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    evt["_dedup_hash"] = _hash_event(evt)
                    events.append(evt)
                except json.JSONDecodeError:
                    logger.warning("Malformed event line in %s, skipping", filepath.name)

        if not events:
            filepath.unlink(missing_ok=True)
            return

        # Batch INSERT with ON CONFLICT DO NOTHING (idempotent)
        for i in range(0, len(events), self.batch_size):
            batch = events[i : i + self.batch_size]
            await db_writer(batch)

        # Success → delete file
        filepath.unlink(missing_ok=True)
        logger.info("Drained %d events from %s", len(events), filepath.name)
