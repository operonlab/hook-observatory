"""Memory-adaptive batch runner — 3-threshold water level concurrency control.

Inspired by Crawl4AI's MemoryAdaptiveDispatcher.
See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import psutil

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveConfig:
    """Three-threshold water level configuration."""

    max_concurrent: int = 4
    memory_threshold: float = 0.80  # enter pressure mode, pause new tasks
    critical_threshold: float = 0.90  # requeue / shed load
    recovery_threshold: float = 0.70  # exit pressure mode, resume
    check_interval: float = 2.0  # seconds between memory checks
    task_timeout: float = 300.0  # per-task timeout in seconds


@dataclass
class _Stats:
    active_tasks: int = 0
    completed: int = 0
    failed: int = 0
    pressure_events: int = 0
    peak_memory: float = 0.0


class MemoryAdaptiveRunner:
    """Run async tasks with memory-aware concurrency control.

    Usage::

        runner = MemoryAdaptiveRunner(AdaptiveConfig(max_concurrent=4))
        results = await runner.run_batch(items, process_fn)

    Results preserve input order.  Failed items return the Exception instead
    of raising, so the caller can inspect partial results.
    """

    def __init__(self, config: AdaptiveConfig | None = None) -> None:
        self._cfg = config or AdaptiveConfig()
        self._sem = asyncio.Semaphore(self._cfg.max_concurrent)
        self._resume = asyncio.Event()  # set = OK to proceed, clear = under pressure
        self._resume.set()
        self._under_pressure = False
        self._stats = _Stats()
        self._active_tasks: dict[int, asyncio.Task[Any]] = {}  # idx → task

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_batch(
        self,
        items: list[Any],
        processor: Callable[[Any], Awaitable[T]],
        *,
        on_pressure: Callable[[], Awaitable[None]] | None = None,
    ) -> list[T | Exception]:
        """Process *items* concurrently, returning results in the same order."""
        results: list[T | Exception] = [Exception("not started")] * len(items)
        self._stats = _Stats()

        monitor = asyncio.create_task(self._monitor(on_pressure))
        try:
            await asyncio.gather(
                *[self._dispatch(i, item, processor, results) for i, item in enumerate(items)]
            )
        finally:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass

        return results

    @property
    def stats(self) -> dict[str, Any]:
        """Current run statistics."""
        return {
            "active_tasks": self._stats.active_tasks,
            "completed": self._stats.completed,
            "failed": self._stats.failed,
            "pressure_events": self._stats.pressure_events,
            "peak_memory": round(self._stats.peak_memory, 2),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        idx: int,
        item: Any,
        processor: Callable[[Any], Awaitable[T]],
        results: list[T | Exception],
    ) -> None:
        # Wait until memory pressure clears before acquiring semaphore slot.
        await self._resume.wait()

        async with self._sem:
            self._stats.active_tasks += 1
            task = asyncio.current_task()
            assert task is not None
            self._active_tasks[idx] = task
            try:
                results[idx] = await asyncio.wait_for(
                    processor(item), timeout=self._cfg.task_timeout
                )
                self._stats.completed += 1
            except Exception as exc:
                results[idx] = exc
                self._stats.failed += 1
                logger.warning("adaptive: task %d failed: %s", idx, exc)
            finally:
                self._stats.active_tasks -= 1
                self._active_tasks.pop(idx, None)

    async def _monitor(self, on_pressure: Callable[[], Awaitable[None]] | None) -> None:
        """Background loop: sample memory and set/clear pressure event."""
        cfg = self._cfg
        while True:
            await asyncio.sleep(cfg.check_interval)
            mem_pct = psutil.virtual_memory().percent / 100.0
            if mem_pct > self._stats.peak_memory:
                self._stats.peak_memory = mem_pct

            if mem_pct >= cfg.critical_threshold:
                if not self._under_pressure:
                    self._stats.pressure_events += 1
                    self._under_pressure = True
                    self._resume.clear()
                    logger.warning(
                        "adaptive: CRITICAL memory %.1f%% — cancelling oldest task",
                        mem_pct * 100,
                    )
                # Cancel the task with the lowest index (oldest dispatched).
                if self._active_tasks:
                    oldest_idx = min(self._active_tasks)
                    self._active_tasks[oldest_idx].cancel()
                if on_pressure:
                    await on_pressure()

            elif mem_pct >= cfg.memory_threshold:
                if not self._under_pressure:
                    self._stats.pressure_events += 1
                    self._under_pressure = True
                    self._resume.clear()
                    logger.info("adaptive: pressure mode — memory %.1f%%", mem_pct * 100)
                if on_pressure:
                    await on_pressure()

            elif mem_pct < cfg.recovery_threshold and self._under_pressure:
                self._under_pressure = False
                self._resume.set()
                logger.info("adaptive: pressure cleared — memory %.1f%%", mem_pct * 100)
