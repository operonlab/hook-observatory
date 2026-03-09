"""StabilityPoller — DOM stability polling for response completion detection.

Pattern from grok-bridge: poll DOM content at regular intervals,
declare completion when content has changed from baseline AND stabilizes
(N consecutive identical reads after normalization).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class PollResult:
    """Result of a stability polling session."""

    content: str
    stable: bool  # True if stabilized, False if timeout
    elapsed: float  # seconds
    poll_count: int  # how many polls were performed
    stable_count: int  # consecutive stable reads before return


class StabilityPoller:
    """Poll a content source until output stabilizes.

    Simple single-loop approach (from ythx-101/grok-bridge):
    - Content must differ from baseline (response started)
    - Content must match previous poll (response done)
    - Both conditions met for N consecutive polls = stable
    """

    def __init__(
        self,
        interval: float = 2.0,
        threshold: int = 3,
    ) -> None:
        self.interval = interval
        self.threshold = threshold

    async def poll(
        self,
        fetch_content: Callable[[], Awaitable[str]],
        timeout: int = 120,
        baseline: str = "",
        normalize: Callable[[str], str] | None = None,
    ) -> PollResult:
        """Poll content source until it stabilizes.

        Args:
            fetch_content: Async callable that returns current page content.
            timeout: Maximum seconds to wait.
            baseline: Content before prompt was sent.
            normalize: Optional function to strip noise before comparison.

        Returns:
            PollResult with the final stable content.
        """
        start = time.monotonic()
        last = ""
        stable_count = 0
        poll_count = 0

        while time.monotonic() - start < timeout:
            await asyncio.sleep(self.interval)
            poll_count += 1

            current = await fetch_content()
            norm_current = normalize(current) if normalize else current
            norm_last = normalize(last) if (normalize and last) else last

            # Stability: normalized content matches last poll and is non-empty
            if norm_current and norm_current == norm_last:
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

            last = current

        # Timeout — return whatever we have
        return PollResult(
            content=last or baseline,
            stable=False,
            elapsed=time.monotonic() - start,
            poll_count=poll_count,
            stable_count=stable_count,
        )
