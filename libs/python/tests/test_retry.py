"""
Test suite for workshop.retry — written WITHOUT reading the implementation.
Based solely on function signatures and docstrings (寫測分離 principle).

# MUTATION TARGETS
The following mutations are explicitly targeted by tests in this file:

| Mutation                             | Caught by                                              |
|--------------------------------------|--------------------------------------------------------|
| `2**attempt` → `2*attempt`           | TestCalcDelay::test_exponential_growth                 |
| `min(x, max_delay)` → `max(x,...)`   | TestCalcDelay::test_bounded_by_max_delay               |
| `max_retries - 1` → `max_retries`    | TestWithBackoff::test_call_count_on_persistent_failure |
|                                      | TestAsyncWithBackoff::test_call_count_on_persistent_failure |
|                                      | TestRetryCall::test_call_count_on_persistent_failure   |
| `raise last_exc` → `return None`     | TestWithBackoff::test_all_fail_raises_last_exception   |
|                                      | TestAsyncWithBackoff::test_all_fail_raises_last_exception |
|                                      | TestRetryCall::test_all_fail_raises_last_exception     |
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from workshop.retry import _calc_delay, async_with_backoff, retry_call, with_backoff

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AlwaysFail:
    """Callable that always raises the given exception, counting calls."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.call_count = 0

    def __call__(self, *_, **__):
        self.call_count += 1
        raise self.exc


class _FailNTimes:
    """Callable that raises for the first `n` calls, then returns a value."""

    def __init__(self, n: int, exc: Exception, return_value=42):
        self.n = n
        self.exc = exc
        self.return_value = return_value
        self.call_count = 0

    def __call__(self, *_, **__):
        self.call_count += 1
        if self.call_count <= self.n:
            raise self.exc
        return self.return_value


class _AsyncAlwaysFail:
    """Async callable that always raises."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.call_count = 0

    async def __call__(self, *_, **__):
        self.call_count += 1
        raise self.exc


class _AsyncFailNTimes:
    """Async callable that raises for the first `n` calls."""

    def __init__(self, n: int, exc: Exception, return_value=42):
        self.n = n
        self.exc = exc
        self.return_value = return_value
        self.call_count = 0

    async def __call__(self, *_, **__):
        self.call_count += 1
        if self.call_count <= self.n:
            raise self.exc
        return self.return_value


# ---------------------------------------------------------------------------
# TestCalcDelay
# ---------------------------------------------------------------------------


class TestCalcDelay:
    """Invariant tests for _calc_delay(attempt, base_delay, max_delay)."""

    # ------------------------------------------------------------------
    # Invariant: non-negative
    # MUTATION TARGET: any negation of result
    # ------------------------------------------------------------------

    def test_non_negative_attempt_0(self):
        result = _calc_delay(0, 1.0, 60.0)
        assert result >= 0, "Delay must be non-negative at attempt 0"

    def test_non_negative_attempt_10(self):
        result = _calc_delay(10, 1.0, 60.0)
        assert result >= 0, "Delay must be non-negative at high attempt count"

    def test_non_negative_tiny_base(self):
        result = _calc_delay(0, 0.001, 60.0)
        assert result >= 0, "Delay must be non-negative with tiny base_delay"

    # ------------------------------------------------------------------
    # Invariant: bounded by max_delay (with 10% jitter allowance)
    # MUTATION TARGET: `min(x, max_delay)` → `max(x, max_delay)`
    # ------------------------------------------------------------------

    def test_bounded_by_max_delay(self):
        max_delay = 30.0
        # At attempt=10, base * 2^10 = 1024 >> max_delay; must be capped
        result = _calc_delay(10, 1.0, max_delay)
        assert result <= max_delay * 1.1, (
            f"Delay {result} exceeded max_delay {max_delay} by more than 10%"
        )

    def test_bounded_small_max(self):
        max_delay = 2.0
        result = _calc_delay(5, 1.0, max_delay)
        assert result <= max_delay * 1.1

    def test_bounded_at_attempt_0(self):
        max_delay = 0.5
        result = _calc_delay(0, 1.0, max_delay)
        assert result <= max_delay * 1.1

    # ------------------------------------------------------------------
    # Invariant: exponential growth — base * 2^attempt pattern
    # MUTATION TARGET: `2**attempt` → `2*attempt`
    # ------------------------------------------------------------------

    def test_exponential_growth_attempt_0(self):
        """At attempt 0: result ≈ base * 2^0 = base_delay (within jitter)."""
        base = 1.0
        max_d = 60.0
        result = _calc_delay(0, base, max_d)
        # base * 2^0 = 1.0; jitter may add up to base, so expect [0, ~2.0]
        assert 0 <= result <= base * 2 + 1.0, (
            f"attempt=0 delay {result} is far from expected ~{base}"
        )

    def test_exponential_growth_doubles_per_attempt(self):
        """
        Verify exponential (not linear) scaling.
        Linear mutation `2*attempt` produces 0, 2, 4, 6, ... which grows much
        slower than exponential 1, 2, 4, 8, ... — we compare attempt=1 vs attempt=4.
        Under linear: 2*1=2, 2*4=8 → ratio ≈ 4.
        Under exponential: 2^1=2, 2^4=16 → ratio ≈ 8.
        We require ratio > 5 to distinguish.
        """
        base = 1.0
        max_d = 60.0
        # Run multiple trials to smooth jitter variance
        ratios = []
        for _ in range(20):
            d1 = _calc_delay(1, base, max_d)
            d4 = _calc_delay(4, base, max_d)
            if d1 > 0:
                ratios.append(d4 / d1)

        median_ratio = sorted(ratios)[len(ratios) // 2]
        assert median_ratio > 4.0, (
            f"Expected exponential growth ratio > 4, got median {median_ratio:.2f}. "
            "Possible mutation: 2**attempt → 2*attempt"
        )

    def test_exponential_growth_attempt_3_approximate(self):
        """
        At attempt=3 with base=1.0: base * 2^3 = 8.0.
        Jitter may vary, but the central tendency should be ~8.0.
        Sample multiple times and check median.
        """
        base = 1.0
        max_d = 60.0
        samples = [_calc_delay(3, base, max_d) for _ in range(30)]
        median = sorted(samples)[len(samples) // 2]
        # Expect median in [6.0, 12.0] to catch linear mutation (which gives 3*2=6)
        # but be lenient enough for jitter
        assert median >= 5.0, f"Median delay at attempt=3 ({median:.2f}) too low; expected ~8.0"

    # ------------------------------------------------------------------
    # Invariant: weak monotonic (accounting for jitter)
    # MUTATION TARGET: swapped exponent / negated exponent
    # ------------------------------------------------------------------

    def test_weak_monotonic_tendency(self):
        """
        _calc_delay(n+1) should generally be larger than _calc_delay(n).
        We allow the 0.8 factor to account for jitter variance.
        Test across many samples.
        """
        base = 1.0
        max_d = 60.0
        violations = 0
        trials = 50
        for _ in range(trials):
            for n in range(0, 5):
                d_n = _calc_delay(n, base, max_d)
                d_n1 = _calc_delay(n + 1, base, max_d)
                # d(n+1) should be > d(n) * 0.8
                if d_n1 < d_n * 0.8 and d_n < max_d * 0.9:
                    violations += 1

        # Allow at most 15% violations due to jitter
        assert violations / (trials * 5) <= 0.15, (
            f"Too many monotonic violations: {violations}/{trials * 5}"
        )


# ---------------------------------------------------------------------------
# TestWithBackoff
# ---------------------------------------------------------------------------


class TestWithBackoff:
    """Invariant tests for the sync @with_backoff decorator."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_on_first_try_calls_fn_once(self):
        """If fn succeeds, fn is called exactly once."""
        with patch("time.sleep"):
            call_count = 0

            @with_backoff(max_retries=3)
            def fn():
                nonlocal call_count
                call_count += 1
                return "ok"

            result = fn()

        assert result == "ok"
        assert call_count == 1

    def test_success_returns_correct_value(self):
        with patch("time.sleep"):

            @with_backoff(max_retries=3)
            def fn():
                return 99

            assert fn() == 99

    def test_no_sleep_on_first_try_success(self):
        """No sleeping should occur if fn succeeds on the first try."""
        with patch("time.sleep") as mock_sleep:

            @with_backoff(max_retries=3)
            def fn():
                return "ok"

            fn()

        mock_sleep.assert_not_called()

    # ------------------------------------------------------------------
    # Retry count invariant
    # MUTATION TARGET: `max_retries - 1` → `max_retries` (would call fn one extra time)
    # ------------------------------------------------------------------

    def test_call_count_on_persistent_failure(self):
        """
        On persistent failure, fn must be called exactly max_retries times
        (1 initial attempt + max_retries - 1 retries = max_retries total).
        """
        with patch("time.sleep"):
            exc = ValueError("boom")
            fn_obj = _AlwaysFail(exc)

            @with_backoff(max_retries=4)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError):
                fn()

        assert fn_obj.call_count == 4, (
            f"Expected 4 calls (max_retries=4), got {fn_obj.call_count}. "
            "Possible mutation: max_retries - 1 → max_retries"
        )

    def test_call_count_max_retries_1(self):
        """With max_retries=1, fn is called exactly once then fails."""
        with patch("time.sleep"):
            exc = RuntimeError("fail")
            fn_obj = _AlwaysFail(exc)

            @with_backoff(max_retries=1)
            def fn():
                return fn_obj()

            with pytest.raises(RuntimeError):
                fn()

        assert fn_obj.call_count == 1

    def test_call_count_max_retries_2(self):
        with patch("time.sleep"):
            exc = OSError("fail")
            fn_obj = _AlwaysFail(exc)

            @with_backoff(max_retries=2)
            def fn():
                return fn_obj()

            with pytest.raises(OSError):
                fn()

        assert fn_obj.call_count == 2

    # ------------------------------------------------------------------
    # All-fail raises invariant
    # MUTATION TARGET: `raise last_exc` → `return None`
    # ------------------------------------------------------------------

    def test_all_fail_raises_last_exception(self):
        """Decorator must propagate (raise) the exception, not return None."""
        with patch("time.sleep"):
            exc = ValueError("last error")
            fn_obj = _AlwaysFail(exc)

            @with_backoff(max_retries=3)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError, match="last error"):
                fn()

    def test_raises_exception_type_not_none(self):
        """Return value after all retries exhausted must not be None."""
        with patch("time.sleep"):

            @with_backoff(max_retries=2)
            def fn():
                raise TypeError("nope")

            result_container = []
            try:
                fn()
            except TypeError:
                result_container.append("raised")
            except Exception:
                result_container.append("wrong_exc")
            else:
                result_container.append("no_exc")

        assert result_container == ["raised"], (
            "Expected TypeError to be raised; got something else. "
            "Possible mutation: raise last_exc → return None"
        )

    # ------------------------------------------------------------------
    # Correct exception (last, not first)
    # ------------------------------------------------------------------

    def test_raises_last_exception_not_first(self):
        """The raised exception is the LAST one thrown, not the first."""
        with patch("time.sleep"):
            call_count = 0
            raised_exceptions = [
                ValueError("first"),
                ValueError("second"),
                ValueError("third"),
            ]

            @with_backoff(max_retries=3)
            def fn():
                nonlocal call_count
                exc = raised_exceptions[call_count]
                call_count += 1
                raise exc

            with pytest.raises(ValueError, match="third"):
                fn()

    # ------------------------------------------------------------------
    # Retryable exception filtering
    # ------------------------------------------------------------------

    def test_non_retryable_exception_raised_immediately(self):
        """A non-retryable exception must be raised without retrying."""
        with patch("time.sleep"):
            call_count = 0

            @with_backoff(max_retries=5, retryable=ValueError)
            def fn():
                nonlocal call_count
                call_count += 1
                raise TypeError("not retryable")

            with pytest.raises(TypeError):
                fn()

        assert call_count == 1, (
            f"Non-retryable exception should not trigger retries; fn called {call_count} times"
        )

    def test_retryable_exception_triggers_retries(self):
        """A matching retryable exception triggers retries."""
        with patch("time.sleep"):
            fn_obj = _AlwaysFail(ValueError("retryable"))

            @with_backoff(max_retries=3, retryable=ValueError)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError):
                fn()

        assert fn_obj.call_count == 3

    def test_success_after_retries_returns_value(self):
        """If fn eventually succeeds, return its value."""
        with patch("time.sleep"):
            fn_obj = _FailNTimes(2, ValueError("temp"), return_value=42)

            @with_backoff(max_retries=5)
            def fn():
                return fn_obj()

            result = fn()

        assert result == 42
        assert fn_obj.call_count == 3  # 2 failures + 1 success

    # ------------------------------------------------------------------
    # on_retry callback
    # ------------------------------------------------------------------

    def test_on_retry_called_on_each_retry(self):
        """on_retry callback is called for each retry (not the first attempt)."""
        with patch("time.sleep"):
            retry_calls = []

            def on_retry(attempt, exc):
                retry_calls.append((attempt, exc))

            fn_obj = _AlwaysFail(ValueError("x"))

            @with_backoff(max_retries=4, on_retry=on_retry)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError):
                fn()

        # on_retry should be called max_retries - 1 times (after each failed attempt
        # that has a subsequent retry), i.e., 3 times for max_retries=4
        assert len(retry_calls) == 3, (
            f"Expected 3 on_retry calls for max_retries=4, got {len(retry_calls)}"
        )

    # ------------------------------------------------------------------
    # sleep is called (delays occur between retries)
    # ------------------------------------------------------------------

    def test_sleep_called_between_retries(self):
        """time.sleep must be called between retries."""
        with patch("time.sleep") as mock_sleep:
            fn_obj = _AlwaysFail(ValueError("x"))

            @with_backoff(max_retries=3)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError):
                fn()

        # 3 total calls, 2 retries → 2 sleep calls
        assert mock_sleep.call_count == 2, (
            f"Expected 2 sleep calls for max_retries=3, got {mock_sleep.call_count}"
        )

    def test_sleep_not_called_after_final_failure(self):
        """No sleep after the last retry (no point waiting before raising)."""
        with patch("time.sleep") as mock_sleep:
            fn_obj = _AlwaysFail(ValueError("x"))

            @with_backoff(max_retries=1)
            def fn():
                return fn_obj()

            with pytest.raises(ValueError):
                fn()

        assert mock_sleep.call_count == 0


# ---------------------------------------------------------------------------
# TestAsyncWithBackoff
# ---------------------------------------------------------------------------


class TestAsyncWithBackoff:
    """Invariant tests for the async @async_with_backoff decorator."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_on_first_try_calls_fn_once(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            call_count = 0

            @async_with_backoff(max_retries=3)
            async def fn():
                nonlocal call_count
                call_count += 1
                return "ok"

            result = asyncio.run(fn())

        assert result == "ok"
        assert call_count == 1

    def test_success_returns_correct_value(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):

            @async_with_backoff(max_retries=3)
            async def fn():
                return 77

            assert asyncio.run(fn()) == 77

    def test_no_sleep_on_first_try_success(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            @async_with_backoff(max_retries=3)
            async def fn():
                return "ok"

            asyncio.run(fn())

        mock_sleep.assert_not_called()

    # ------------------------------------------------------------------
    # Retry count invariant
    # MUTATION TARGET: `max_retries - 1` → `max_retries`
    # ------------------------------------------------------------------

    def test_call_count_on_persistent_failure(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            exc = ValueError("boom")
            fn_obj = _AsyncAlwaysFail(exc)

            @async_with_backoff(max_retries=4)
            async def fn():
                return await fn_obj()

            with pytest.raises(ValueError):
                asyncio.run(fn())

        assert fn_obj.call_count == 4, (
            f"Expected 4 calls (max_retries=4), got {fn_obj.call_count}. "
            "Possible mutation: max_retries - 1 → max_retries"
        )

    def test_call_count_max_retries_1(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            fn_obj = _AsyncAlwaysFail(RuntimeError("fail"))

            @async_with_backoff(max_retries=1)
            async def fn():
                return await fn_obj()

            with pytest.raises(RuntimeError):
                asyncio.run(fn())

        assert fn_obj.call_count == 1

    def test_call_count_max_retries_2(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            fn_obj = _AsyncAlwaysFail(OSError("fail"))

            @async_with_backoff(max_retries=2)
            async def fn():
                return await fn_obj()

            with pytest.raises(OSError):
                asyncio.run(fn())

        assert fn_obj.call_count == 2

    # ------------------------------------------------------------------
    # All-fail raises invariant
    # MUTATION TARGET: `raise last_exc` → `return None`
    # ------------------------------------------------------------------

    def test_all_fail_raises_last_exception(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            fn_obj = _AsyncAlwaysFail(ValueError("last async error"))

            @async_with_backoff(max_retries=3)
            async def fn():
                return await fn_obj()

            with pytest.raises(ValueError, match="last async error"):
                asyncio.run(fn())

    def test_raises_exception_not_returns_none(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):

            @async_with_backoff(max_retries=2)
            async def fn():
                raise TypeError("async nope")

            result_container = []

            async def runner():
                try:
                    await fn()
                except TypeError:
                    result_container.append("raised")
                else:
                    result_container.append("no_exc")

            asyncio.run(runner())

        assert result_container == ["raised"]

    # ------------------------------------------------------------------
    # Correct exception (last)
    # ------------------------------------------------------------------

    def test_raises_last_exception_not_first(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            call_count = 0
            raised_exceptions = [
                ValueError("async first"),
                ValueError("async second"),
                ValueError("async third"),
            ]

            @async_with_backoff(max_retries=3)
            async def fn():
                nonlocal call_count
                exc = raised_exceptions[call_count]
                call_count += 1
                raise exc

            with pytest.raises(ValueError, match="async third"):
                asyncio.run(fn())

    # ------------------------------------------------------------------
    # Retryable filtering
    # ------------------------------------------------------------------

    def test_non_retryable_exception_raised_immediately(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            call_count = 0

            @async_with_backoff(max_retries=5, retryable=ValueError)
            async def fn():
                nonlocal call_count
                call_count += 1
                raise TypeError("not retryable async")

            with pytest.raises(TypeError):
                asyncio.run(fn())

        assert call_count == 1

    def test_success_after_retries_returns_value(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            fn_obj = _AsyncFailNTimes(2, ValueError("temp"), return_value=99)

            @async_with_backoff(max_retries=5)
            async def fn():
                return await fn_obj()

            result = asyncio.run(fn())

        assert result == 99
        assert fn_obj.call_count == 3

    # ------------------------------------------------------------------
    # on_retry callback
    # ------------------------------------------------------------------

    def test_on_retry_called_on_each_retry(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            retry_calls = []

            def on_retry(attempt, exc):
                retry_calls.append((attempt, exc))

            fn_obj = _AsyncAlwaysFail(ValueError("x"))

            @async_with_backoff(max_retries=4, on_retry=on_retry)
            async def fn():
                return await fn_obj()

            with pytest.raises(ValueError):
                asyncio.run(fn())

        assert len(retry_calls) == 3

    # ------------------------------------------------------------------
    # async sleep called between retries
    # ------------------------------------------------------------------

    def test_async_sleep_called_between_retries(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            fn_obj = _AsyncAlwaysFail(ValueError("x"))

            @async_with_backoff(max_retries=3)
            async def fn():
                return await fn_obj()

            with pytest.raises(ValueError):
                asyncio.run(fn())

        assert mock_sleep.call_count == 2

    def test_time_sleep_not_used_in_async_variant(self):
        """Async variant must use asyncio.sleep, never time.sleep."""
        with patch("time.sleep") as mock_time_sleep, patch("asyncio.sleep", new_callable=AsyncMock):
            fn_obj = _AsyncAlwaysFail(ValueError("x"))

            @async_with_backoff(max_retries=3)
            async def fn():
                return await fn_obj()

            with pytest.raises(ValueError):
                asyncio.run(fn())

        mock_time_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# TestRetryCall
# ---------------------------------------------------------------------------


class TestRetryCall:
    """Invariant tests for retry_call (non-decorator inline helper)."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_on_first_try_calls_fn_once(self):
        with patch("time.sleep"):
            call_count = 0

            def fn():
                nonlocal call_count
                call_count += 1
                return "ok"

            result = retry_call(fn, max_retries=3)

        assert result == "ok"
        assert call_count == 1

    def test_success_returns_correct_value(self):
        with patch("time.sleep"):

            def fn():
                return 55

            assert retry_call(fn, max_retries=3) == 55

    def test_passes_args_and_kwargs_to_fn(self):
        with patch("time.sleep"):

            def fn(a, b, keyword=None):
                return (a, b, keyword)

            result = retry_call(fn, 1, 2, max_retries=3, keyword="kw")

        assert result == (1, 2, "kw")

    # ------------------------------------------------------------------
    # Retry count invariant
    # MUTATION TARGET: `max_retries - 1` → `max_retries`
    # ------------------------------------------------------------------

    def test_call_count_on_persistent_failure(self):
        with patch("time.sleep"):
            exc = ValueError("inline boom")
            fn_obj = _AlwaysFail(exc)

            with pytest.raises(ValueError):
                retry_call(fn_obj, max_retries=4)

        assert fn_obj.call_count == 4, (
            f"Expected 4 calls (max_retries=4), got {fn_obj.call_count}. "
            "Possible mutation: max_retries - 1 → max_retries"
        )

    def test_call_count_max_retries_1(self):
        with patch("time.sleep"):
            fn_obj = _AlwaysFail(RuntimeError("fail"))

            with pytest.raises(RuntimeError):
                retry_call(fn_obj, max_retries=1)

        assert fn_obj.call_count == 1

    def test_call_count_max_retries_5(self):
        with patch("time.sleep"):
            fn_obj = _AlwaysFail(OSError("fail"))

            with pytest.raises(OSError):
                retry_call(fn_obj, max_retries=5)

        assert fn_obj.call_count == 5

    # ------------------------------------------------------------------
    # All-fail raises invariant
    # MUTATION TARGET: `raise last_exc` → `return None`
    # ------------------------------------------------------------------

    def test_all_fail_raises_last_exception(self):
        with patch("time.sleep"):
            exc = ValueError("inline last error")
            fn_obj = _AlwaysFail(exc)

            with pytest.raises(ValueError, match="inline last error"):
                retry_call(fn_obj, max_retries=3)

    def test_raises_exception_not_returns_none(self):
        with patch("time.sleep"):

            def fn():
                raise TypeError("inline nope")

            result_container = []
            try:
                retry_call(fn, max_retries=2)
            except TypeError:
                result_container.append("raised")
            else:
                result_container.append("no_exc")

        assert result_container == ["raised"]

    # ------------------------------------------------------------------
    # Correct exception (last)
    # ------------------------------------------------------------------

    def test_raises_last_exception_not_first(self):
        with patch("time.sleep"):
            call_count = 0
            raised_exceptions = [
                ValueError("inline first"),
                ValueError("inline second"),
                ValueError("inline third"),
            ]

            def fn():
                nonlocal call_count
                exc = raised_exceptions[call_count]
                call_count += 1
                raise exc

            with pytest.raises(ValueError, match="inline third"):
                retry_call(fn, max_retries=3)

    # ------------------------------------------------------------------
    # Retryable filtering
    # ------------------------------------------------------------------

    def test_non_retryable_exception_raised_immediately(self):
        with patch("time.sleep"):
            call_count = 0

            def fn():
                nonlocal call_count
                call_count += 1
                raise TypeError("not retryable inline")

            with pytest.raises(TypeError):
                retry_call(fn, max_retries=5, retryable=ValueError)

        assert call_count == 1

    def test_retryable_tuple_of_exceptions(self):
        """Accepts a tuple of retryable exception types."""
        with patch("time.sleep"):
            fn_obj = _AlwaysFail(OSError("retryable tuple"))

            with pytest.raises(OSError):
                retry_call(fn_obj, max_retries=3, retryable=(ValueError, OSError))

        assert fn_obj.call_count == 3

    def test_success_after_retries_returns_value(self):
        with patch("time.sleep"):
            fn_obj = _FailNTimes(2, ValueError("temp"), return_value=77)
            result = retry_call(fn_obj, max_retries=5)

        assert result == 77
        assert fn_obj.call_count == 3

    # ------------------------------------------------------------------
    # sleep behavior
    # ------------------------------------------------------------------

    def test_sleep_called_between_retries(self):
        with patch("time.sleep") as mock_sleep:
            fn_obj = _AlwaysFail(ValueError("x"))

            with pytest.raises(ValueError):
                retry_call(fn_obj, max_retries=3)

        assert mock_sleep.call_count == 2

    def test_sleep_not_called_on_first_try_success(self):
        with patch("time.sleep") as mock_sleep:

            def fn():
                return "ok"

            retry_call(fn, max_retries=3)

        mock_sleep.assert_not_called()

    # ------------------------------------------------------------------
    # NOTE: retry_call does NOT expose on_retry (see signature — **kwargs
    # are forwarded to func, not to the retry mechanism itself).
    # on_retry is a decorator-only feature (with_backoff / async_with_backoff).
    # ------------------------------------------------------------------
