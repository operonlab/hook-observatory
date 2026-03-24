"""Exponential backoff retry utilities.

Usage:
    from workshop.retry import with_backoff, async_with_backoff

    @with_backoff(max_retries=3, base_delay=1.0)
    def fetch_data():
        ...

    @async_with_backoff(max_retries=3, base_delay=1.0)
    async def async_fetch():
        ...

    # Or inline:
    result = retry_call(lambda: risky_op(), max_retries=3)
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _calc_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Calculate delay with jitter: base * 2^attempt + random jitter."""
    delay = min(base_delay * (2**attempt), max_delay)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


def _should_retry(exc: Exception, retryable: Any) -> bool:
    """Check if an exception should be retried.

    retryable can be:
      - A type or tuple of types: isinstance check
      - A callable(exc) -> bool: custom filter
    """
    if callable(retryable) and not isinstance(retryable, type):
        return retryable(exc)
    return isinstance(exc, retryable)


def with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable: type[Exception]
    | tuple[type[Exception], ...]
    | Callable[[Exception], bool] = Exception,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Callable:
    """Sync decorator for exponential backoff retry."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if not _should_retry(exc, retryable):
                        raise
                    last_exc = exc
                    if attempt < max_retries - 1:
                        delay = _calc_delay(attempt, base_delay, max_delay)
                        logger.warning(
                            "retry_backoff",
                            extra={
                                "func": func.__name__,
                                "attempt": attempt + 1,
                                "delay": round(delay, 2),
                                "error": str(exc),
                            },
                        )
                        if on_retry:
                            on_retry(attempt + 1, exc)
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def async_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable: type[Exception]
    | tuple[type[Exception], ...]
    | Callable[[Exception], bool] = Exception,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Callable:
    """Async decorator for exponential backoff retry."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if not _should_retry(exc, retryable):
                        raise
                    last_exc = exc
                    if attempt < max_retries - 1:
                        delay = _calc_delay(attempt, base_delay, max_delay)
                        logger.warning(
                            "retry_backoff",
                            extra={
                                "func": func.__name__,
                                "attempt": attempt + 1,
                                "delay": round(delay, 2),
                                "error": str(exc),
                            },
                        )
                        if on_retry:
                            on_retry(attempt + 1, exc)
                        await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def retry_call(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable: type[Exception]
    | tuple[type[Exception], ...]
    | Callable[[Exception], bool] = Exception,
    **kwargs: Any,
) -> T:
    """Inline retry helper (non-decorator usage)."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if not _should_retry(exc, retryable):
                raise
            last_exc = exc
            if attempt < max_retries - 1:
                delay = _calc_delay(attempt, base_delay, max_delay)
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]
