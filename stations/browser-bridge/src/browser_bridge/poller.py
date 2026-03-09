"""StabilityPoller — DOM stability polling for response completion detection.

Pattern learned from grok-bridge: poll DOM content at regular intervals,
declare completion when content stabilizes (N consecutive identical reads).

This is more robust than:
- hardcoded waitForTimeout (too long or too short)
- waiting for specific selectors (breaks when UI changes)
- WebSocket/SSE monitoring (requires access to page internals)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Awaitable


@dataclass
class PollResult:
    """Result of a stability polling session."""
    content: str
    stable: bool          # True if stabilized, False if timeout
    elapsed: float        # seconds
    poll_count: int       # how many polls were performed
    stable_count: int     # consecutive stable reads before return


class StabilityPoller:
    """Poll a content source until output stabilizes.

    Args:
        interval: Seconds between polls (default 2.0)
        threshold: Consecutive identical reads to declare stable (default 3)
        min_change: Minimum content length change to consider "response started"
    """

    def __init__(
        self,
        interval: float = 2.0,
        threshold: int = 3,
        min_change: int = 50,
    ) -> None:
        self.interval = interval
        self.threshold = threshold
        self.min_change = min_change

    async def poll(
        self,
        fetch_content: Callable[[], Awaitable[str]],
        timeout: int = 120,
        baseline: str = "",
    ) -> PollResult:
        """Poll content source until it stabilizes.

        Args:
            fetch_content: Async callable that returns current page content.
            timeout: Maximum seconds to wait.
            baseline: Content before prompt was sent (to detect response start).

        Returns:
            PollResult with the final stable content.
        """
        start = time.monotonic()
        last_content = ""
        stable_count = 0
        poll_count = 0
        response_detected = False

        while time.monotonic() - start < timeout:
            await asyncio.sleep(self.interval)
            poll_count += 1

            current = await fetch_content()

            # Phase 1: Wait for response to appear
            if not response_detected:
                if len(current) > len(baseline) + self.min_change:
                    response_detected = True
                last_content = current
                continue

            # Phase 2: Wait for response to stabilize
            if current and current == last_content:
                stable_count += 1
                if stable_count >= self.threshold:
                    return PollResult(
                        content=current,
                        stable=True,
                        elapsed=time.monotonic() - start,
                        poll_count=poll_count,
                        stable_count=stable_count,
                    )
            else:
                stable_count = 0

            last_content = current

        # Timeout — return whatever we have
        return PollResult(
            content=last_content or baseline,
            stable=False,
            elapsed=time.monotonic() - start,
            poll_count=poll_count,
            stable_count=stable_count,
        )
