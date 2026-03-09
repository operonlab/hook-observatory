"""Domain-aware async rate limiter for outbound HTTP requests.

Design reference: AD-12 (Outbound Rate Limiting), inspired by the
per-domain throttling pattern in crawl4ai/async_dispatcher.py.

Key behaviours:
- Per-domain asyncio.Lock prevents concurrent thundering-herd
- Exponential backoff with ±25% jitter on 429/503 responses
- Gradual delay reduction on sustained success (75% decay per request)
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class DomainState:
    """Mutable per-domain throttle state."""

    last_request_time: float = 0.0
    current_delay: float = 0.0
    fail_count: int = 0
    success_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RateLimiter:
    """Async, per-domain rate limiter with exponential backoff.

    Usage::

        limiter = RateLimiter()
        await limiter.acquire("https://example.com/page")
        response = await http_client.get(url)
        if response.status == 429:
            limiter.report_failure("https://example.com/page", 429)
        else:
            limiter.report_success("https://example.com/page")

    Args:
        base_delay: ``(min, max)`` seconds for initial/recovery delay range.
        max_delay: Absolute ceiling for any computed delay (seconds).
        backoff_factor: Multiplier applied on each failure (default 2x).
        rate_limit_codes: HTTP status codes treated as rate-limit signals.
    """

    def __init__(
        self,
        base_delay: tuple[float, float] = (1.0, 3.0),
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        rate_limit_codes: list[int] | None = None,
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.rate_limit_codes: list[int] = rate_limit_codes or [429, 503]
        self._domains: dict[str, DomainState] = {}
        self._registry_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_domain(self, url: str) -> str:
        return urlparse(url).netloc or url

    async def _get_state(self, domain: str) -> DomainState:
        """Return existing state or create one (registry-level lock)."""
        if domain not in self._domains:
            async with self._registry_lock:
                if domain not in self._domains:
                    self._domains[domain] = DomainState()
        return self._domains[domain]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, url: str) -> None:
        """Block until the domain quota allows the next request.

        Serialises concurrent callers for the same domain via a per-domain
        lock, then sleeps for any remaining inter-request delay.
        """
        domain = self._extract_domain(url)
        state = await self._get_state(domain)

        async with state.lock:
            now = time.monotonic()
            if state.last_request_time:
                elapsed = now - state.last_request_time
                wait = max(0.0, state.current_delay - elapsed)
                if wait > 0:
                    await asyncio.sleep(wait)

            if state.current_delay == 0.0:
                state.current_delay = random.uniform(*self.base_delay)  # noqa: S311

            state.last_request_time = time.monotonic()

    def report_success(self, url: str) -> None:
        """Decay the domain delay by 25% after a successful response."""
        domain = self._extract_domain(url)
        state = self._domains.get(domain)
        if state is None:
            return
        state.success_count += 1
        state.fail_count = 0
        state.current_delay = max(
            random.uniform(*self.base_delay),  # noqa: S311
            state.current_delay * 0.75,
        )

    def report_failure(self, url: str, status_code: int) -> None:
        """Apply exponential backoff with ±25% jitter on rate-limit codes."""
        domain = self._extract_domain(url)
        state = self._domains.get(domain)
        if state is None:
            return
        if status_code in self.rate_limit_codes:
            state.fail_count += 1
            jitter = random.uniform(0.75, 1.25)  # noqa: S311
            state.current_delay = min(
                state.current_delay * self.backoff_factor * jitter,
                self.max_delay,
            )
