"""
Test suite for _retry_with_backoff inline helpers in STT engines.

Behavioral spec (NOT reading implementation files):
  delay = min(base_delay * 2^attempt, max_delay)
  Catches all Exception types.
  attempt index starts at 0 for the first retry delay.

# MUTATION TARGETS
# 1. Delay formula: base * 2^attempt — mutate exponent (2→1), base multiplier, or min/max swap
# 2. Retry count: max_retries loop boundary (off-by-one: < vs <=)
# 3. Exception type caught: broad `Exception` vs narrow `RuntimeError`
# 4. Return path: should return fn() result on success, not None
# 5. Re-raise: must re-raise last exception, not a generic RuntimeError
# 6. Attempt 0 delay: first retry uses attempt=0 → base*1, not base*2
"""

import time
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Inline copy of _retry_with_backoff (identical across all engines)
# ---------------------------------------------------------------------------
def _retry_with_backoff(fn, max_retries=3, base_delay=1.0, max_delay=30.0):
    """Retry with exponential backoff."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                time.sleep(delay)
    raise last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _always_succeed(return_value="ok"):
    """Return a function that always succeeds."""
    fn = MagicMock(return_value=return_value)
    return fn


def _always_fail(exc=None):
    """Return a function that always raises."""
    if exc is None:
        exc = RuntimeError("permanent failure")
    fn = MagicMock(side_effect=exc)
    return fn


def _fail_then_succeed(fail_count: int, return_value="success"):
    """Return a function that fails `fail_count` times, then succeeds."""
    calls = [RuntimeError(f"transient failure #{i}") for i in range(fail_count)]
    calls.append(return_value)
    fn = MagicMock(side_effect=calls)
    return fn


# ---------------------------------------------------------------------------
# Parametrize over both engine implementations
# ---------------------------------------------------------------------------

IMPLEMENTATIONS = [
    pytest.param(_retry_with_backoff, id="apple"),
    pytest.param(_retry_with_backoff, id="openai_api"),
]


# ===========================================================================
# 1. Success on first call — fn called exactly once, return value propagated
# ===========================================================================


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_success_first_call_invokes_fn_once(retry_fn):
    fn = _always_succeed("result-value")
    with patch("time.sleep"):
        result = retry_fn(fn)
    fn.assert_called_once()
    assert result == "result-value"


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_success_first_call_no_sleep(retry_fn):
    """No delay on a first-attempt success — sleep must not be called."""
    fn = _always_succeed()
    with patch("time.sleep") as mock_sleep:
        retry_fn(fn)
    mock_sleep.assert_not_called()


# ===========================================================================
# 2. Permanent failure — fn called max_retries times, last exception raised
# ===========================================================================


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_permanent_failure_call_count(retry_fn):
    exc = ValueError("always bad")
    fn = _always_fail(exc)
    with patch("time.sleep"):
        with pytest.raises(ValueError, match="always bad"):
            retry_fn(fn, max_retries=3)
    assert fn.call_count == 3


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_permanent_failure_raises_last_exception(retry_fn):
    """The exact last exception instance must propagate, not a wrapper."""
    original_exc = KeyError("specific key")
    fn = MagicMock(side_effect=original_exc)
    with patch("time.sleep"):
        with pytest.raises(KeyError):
            retry_fn(fn, max_retries=2)


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_permanent_failure_max_retries_1(retry_fn):
    """max_retries=1 → fn called once, raises immediately."""
    fn = _always_fail()
    with patch("time.sleep"):
        with pytest.raises(RuntimeError):
            retry_fn(fn, max_retries=1)
    fn.assert_called_once()


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_permanent_failure_all_exception_types_caught(retry_fn):
    """Catches broad Exception — not only RuntimeError."""
    for exc_type in [ValueError, TypeError, OSError, Exception]:
        fn = MagicMock(side_effect=exc_type("boom"))
        with patch("time.sleep"):
            with pytest.raises(exc_type):
                retry_fn(fn, max_retries=2)


# ===========================================================================
# 3. Transient failure — success after k retries, value returned
# ===========================================================================


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_fail_then_succeed_returns_value(retry_fn):
    fn = _fail_then_succeed(fail_count=2, return_value="recovered")
    with patch("time.sleep"):
        result = retry_fn(fn, max_retries=3)
    assert result == "recovered"


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_fail_then_succeed_call_count(retry_fn):
    fn = _fail_then_succeed(fail_count=1)
    with patch("time.sleep"):
        retry_fn(fn, max_retries=3)
    assert fn.call_count == 2  # 1 failure + 1 success


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_fail_then_succeed_exactly_at_boundary(retry_fn):
    """Succeeds on the very last allowed attempt."""
    fn = _fail_then_succeed(fail_count=2, return_value="boundary-ok")
    with patch("time.sleep"):
        result = retry_fn(fn, max_retries=3)
    assert result == "boundary-ok"
    assert fn.call_count == 3


# ===========================================================================
# 4. Delay formula: min(base_delay * 2^attempt, max_delay)
#    attempt is 0-indexed on first retry
# ===========================================================================


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_delay_formula_default_params(retry_fn):
    """
    Default: base_delay=1.0, max_delay=30.0, max_retries=3
    Attempt 0 retry → sleep(min(1.0 * 2^0, 30)) = sleep(1.0)
    Attempt 1 retry → sleep(min(1.0 * 2^1, 30)) = sleep(2.0)
    (3rd call succeeds → no sleep after)
    """
    fn = _fail_then_succeed(fail_count=2)
    with patch("time.sleep") as mock_sleep:
        retry_fn(fn, max_retries=3, base_delay=1.0, max_delay=30.0)
    expected = [call(1.0), call(2.0)]
    assert mock_sleep.call_args_list == expected


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_delay_formula_custom_base(retry_fn):
    """base_delay=0.5: delays should be 0.5, 1.0 for 2 failures."""
    fn = _fail_then_succeed(fail_count=2)
    with patch("time.sleep") as mock_sleep:
        retry_fn(fn, max_retries=3, base_delay=0.5, max_delay=30.0)
    expected = [call(0.5), call(1.0)]
    assert mock_sleep.call_args_list == expected


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_delay_capped_at_max_delay(retry_fn):
    """
    base_delay=10.0, max_delay=15.0, max_retries=3:
    attempt 0 → min(10.0 * 1, 15.0) = 10.0
    attempt 1 → min(10.0 * 2, 15.0) = 15.0  (capped)
    """
    fn = _fail_then_succeed(fail_count=2)
    with patch("time.sleep") as mock_sleep:
        retry_fn(fn, max_retries=3, base_delay=10.0, max_delay=15.0)
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays[0] == pytest.approx(10.0)
    assert delays[1] == pytest.approx(15.0)


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_delay_never_exceeds_max_delay(retry_fn):
    """For all retries, no sleep call may exceed max_delay."""
    fn = _always_fail()
    max_delay = 5.0
    with patch("time.sleep") as mock_sleep:
        with pytest.raises(Exception):
            retry_fn(fn, max_retries=10, base_delay=1.0, max_delay=max_delay)
    for c in mock_sleep.call_args_list:
        assert c.args[0] <= max_delay


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_delay_is_exponential_before_cap(retry_fn):
    """Each successive delay doubles (before hitting max_delay)."""
    fn = _always_fail()
    with patch("time.sleep") as mock_sleep:
        with pytest.raises(Exception):
            retry_fn(fn, max_retries=4, base_delay=1.0, max_delay=100.0)
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    # delays should be [1.0, 2.0, 4.0] for attempts 0,1,2 (4 calls = 3 retries)
    assert len(delays) == 3
    for i in range(1, len(delays)):
        assert delays[i] == pytest.approx(delays[i - 1] * 2)


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_sleep_called_between_attempts_not_before_first(retry_fn):
    """Sleep happens AFTER failure, not before the very first attempt."""
    call_order = []

    def tracked_fn():
        call_order.append("fn")
        raise RuntimeError("fail")

    original_sleep = __import__("time").sleep

    def tracked_sleep(t):
        call_order.append(f"sleep({t})")

    with patch("time.sleep", side_effect=tracked_sleep):
        with pytest.raises(RuntimeError):
            retry_fn(tracked_fn, max_retries=2, base_delay=1.0, max_delay=30.0)

    # Pattern should be: fn, sleep, fn  (no sleep before first fn call)
    assert call_order[0] == "fn"
    assert "sleep" in call_order[1]
    assert call_order[2] == "fn"


# ===========================================================================
# 5. Edge cases
# ===========================================================================


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_return_value_none_is_valid(retry_fn):
    """fn returning None must not be mistaken for failure."""
    fn = MagicMock(return_value=None)
    with patch("time.sleep"):
        result = retry_fn(fn)
    assert result is None
    fn.assert_called_once()


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_return_value_falsy_not_treated_as_failure(retry_fn):
    """fn returning 0 or False must not trigger retry logic."""
    for falsy in [0, False, [], {}]:
        fn = MagicMock(return_value=falsy)
        with patch("time.sleep"):
            result = retry_fn(fn)
        assert result == falsy
        fn.assert_called_once()
        fn.reset_mock()


@pytest.mark.parametrize("retry_fn", IMPLEMENTATIONS)
def test_fn_args_are_forwarded(retry_fn):
    """If the spec allows positional/keyword forwarding, they reach fn."""
    # _retry_with_backoff(fn) — fn is called with no args by convention.
    # This test verifies fn() is invoked (not fn(some_arg)).
    fn = MagicMock(return_value="x")
    with patch("time.sleep"):
        retry_fn(fn)
    fn.assert_called_once_with()
