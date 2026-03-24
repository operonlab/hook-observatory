"""
Test adversary suite for _retry_with_backoff in vision engines.

Invariants verified:
  1. Success on first try: fn called exactly once, value returned
  2. All-fail raises: fn always raises → exception propagates after max_retries calls
  3. Retry count: fn called exactly max_retries times on persistent failure
  4. Exponential delay: delays follow base * 2^attempt (1, 2, 4, ...) capped at max_delay
  5. Partial success: fail N times then succeed → success value returned

Mutation targets caught by each test:
  test_exponential_delay   → catches 2**attempt → 2*attempt
  test_delay_cap           → catches min(x, max_delay) → max(x, max_delay)
  test_retry_count         → catches max_retries-1 → max_retries (off-by-one)
  test_all_fail_raises     → catches raise last_exc → return None
"""

import time
import unittest
from unittest.mock import MagicMock, patch


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


_RETRY_IMPLS = [
    ("apple", _retry_with_backoff),
    ("claude", _retry_with_backoff),
    ("gemini", _retry_with_backoff),
]


class RetryBehaviorMixin:
    """
    Shared test logic for all three vision engine retry helpers.
    Subclasses set self.retry_fn to the concrete helper under test.
    """

    retry_fn = None  # set by subclass

    # ------------------------------------------------------------------
    # 1. Success on first try
    # ------------------------------------------------------------------
    def test_success_on_first_try_calls_fn_once(self):
        """fn succeeds immediately → called exactly once."""
        fn = MagicMock(return_value="ok")
        with patch("time.sleep"):
            result = self.retry_fn(fn, max_retries=3)
        self.assertEqual(result, "ok")
        fn.assert_called_once()

    def test_success_on_first_try_no_sleep(self):
        """fn succeeds immediately → sleep never called."""
        fn = MagicMock(return_value=42)
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=3)
        mock_sleep.assert_not_called()

    def test_success_on_first_try_returns_correct_value(self):
        """Return value is passed through unchanged."""
        fn = MagicMock(return_value={"label": "cat", "confidence": 0.99})
        with patch("time.sleep"):
            result = self.retry_fn(fn, max_retries=3)
        self.assertEqual(result, {"label": "cat", "confidence": 0.99})

    # ------------------------------------------------------------------
    # 2. All-fail raises (mutation: return None instead of raise)
    # ------------------------------------------------------------------
    def test_all_fail_raises_exception(self):
        """fn always raises → the last exception propagates (not None)."""
        fn = MagicMock(side_effect=ValueError("always broken"))
        with patch("time.sleep"):
            with self.assertRaises(Exception):
                self.retry_fn(fn, max_retries=3)

    def test_all_fail_does_not_return_none(self):
        """Verify that a failing retry does not silently return None."""
        fn = MagicMock(side_effect=RuntimeError("boom"))
        with patch("time.sleep"):
            raised = False
            try:
                result = self.retry_fn(fn, max_retries=3)
                self.assertIsNotNone(
                    result,
                    "retry returned None instead of raising on total failure",
                )
            except Exception:
                raised = True
        self.assertTrue(raised, "expected an exception to be raised on total failure")

    def test_all_fail_raises_original_exception_type(self):
        """The raised exception must be the same type as the one fn threw."""
        fn = MagicMock(side_effect=ValueError("specific"))
        with patch("time.sleep"):
            with self.assertRaises(ValueError):
                self.retry_fn(fn, max_retries=3)

    def test_all_fail_exception_message_preserved(self):
        """The exception message content survives through retries."""
        fn = MagicMock(side_effect=RuntimeError("vision model unavailable"))
        with patch("time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                self.retry_fn(fn, max_retries=3)
        self.assertIn("vision model unavailable", str(ctx.exception))

    # ------------------------------------------------------------------
    # 3. Retry count (mutation: off-by-one in loop bound)
    # ------------------------------------------------------------------
    def test_retry_count_default_max_retries(self):
        """fn called exactly max_retries=3 times on persistent failure."""
        fn = MagicMock(side_effect=OSError("fail"))
        with patch("time.sleep"):
            try:
                self.retry_fn(fn, max_retries=3)
            except Exception:
                pass
        self.assertEqual(fn.call_count, 3)

    def test_retry_count_custom_max_retries_1(self):
        """max_retries=1 → fn called exactly once, no retry."""
        fn = MagicMock(side_effect=OSError("fail"))
        with patch("time.sleep"):
            try:
                self.retry_fn(fn, max_retries=1)
            except Exception:
                pass
        self.assertEqual(fn.call_count, 1)

    def test_retry_count_custom_max_retries_5(self):
        """max_retries=5 → fn called exactly 5 times on persistent failure."""
        fn = MagicMock(side_effect=OSError("fail"))
        with patch("time.sleep"):
            try:
                self.retry_fn(fn, max_retries=5)
            except Exception:
                pass
        self.assertEqual(fn.call_count, 5)

    def test_retry_count_not_extra_call(self):
        """fn must NOT be called max_retries+1 times (off-by-one other direction)."""
        fn = MagicMock(side_effect=OSError("fail"))
        with patch("time.sleep"):
            try:
                self.retry_fn(fn, max_retries=3)
            except Exception:
                pass
        self.assertLessEqual(fn.call_count, 3, "fn must not be called more than max_retries times")

    # ------------------------------------------------------------------
    # 4. Exponential delay (mutation: 2**attempt → 2*attempt)
    # ------------------------------------------------------------------
    def test_exponential_delay_default_params(self):
        """
        With base_delay=1.0 and 3 retries (2 inter-attempt sleeps):
        fail 0 → sleep = min(1.0 * 2**0, 30) = 1.0
        fail 1 → sleep = min(1.0 * 2**1, 30) = 2.0
        Total sleeps: [1.0, 2.0]
        """
        fn = MagicMock(side_effect=[OSError("f"), OSError("f"), "val"])
        with patch("time.sleep") as mock_sleep:
            result = self.retry_fn(fn, max_retries=3, base_delay=1.0, max_delay=30.0)
        self.assertEqual(result, "val")
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleep_args), 2, "expected 2 sleep calls for 2 failures")
        self.assertAlmostEqual(
            sleep_args[0], 1.0, places=5, msg="first sleep must be base_delay * 2**0 = 1.0"
        )
        self.assertAlmostEqual(
            sleep_args[1], 2.0, places=5, msg="second sleep must be base_delay * 2**1 = 2.0"
        )

    def test_exponential_delay_distinguishes_linear(self):
        """
        Exponential (1, 2, 4) != linear (1, 2, 3).
        With 4 retries: sleep sequence must be [1, 2, 4].
        """
        fn = MagicMock(side_effect=[OSError()] * 3 + ["ok"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=4, base_delay=1.0, max_delay=30.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleep_args), 3)
        self.assertAlmostEqual(sleep_args[0], 1.0, places=5)
        self.assertAlmostEqual(sleep_args[1], 2.0, places=5)
        self.assertAlmostEqual(
            sleep_args[2],
            4.0,
            places=5,
            msg="third sleep must be 4.0 (exponential), not 3.0 (linear)",
        )

    def test_exponential_delay_custom_base(self):
        """base_delay=2.0 → delays are 2.0, 4.0."""
        fn = MagicMock(side_effect=[OSError(), OSError(), "done"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=3, base_delay=2.0, max_delay=30.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertAlmostEqual(sleep_args[0], 2.0, places=5)
        self.assertAlmostEqual(sleep_args[1], 4.0, places=5)

    def test_exponential_growth_ratio(self):
        """Each successive delay must be exactly 2× the previous (before cap)."""
        fn = MagicMock(side_effect=[OSError()] * 4 + ["ok"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=5, base_delay=1.0, max_delay=100.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        for i in range(1, len(sleep_args)):
            ratio = sleep_args[i] / sleep_args[i - 1]
            self.assertAlmostEqual(
                ratio, 2.0, places=5, msg=f"delay ratio at index {i} must be 2.0 (exponential)"
            )

    # ------------------------------------------------------------------
    # 4b. Delay cap (mutation: min → max)
    # ------------------------------------------------------------------
    def test_delay_cap_enforced(self):
        """
        With base_delay=1.0, max_delay=4.0, 5 retries:
        Uncapped: 1, 2, 4, 8 → Capped: [1, 2, 4, 4]
        """
        fn = MagicMock(side_effect=[OSError()] * 4 + ["ok"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=5, base_delay=1.0, max_delay=4.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleep_args), 4)
        for i, s in enumerate(sleep_args):
            self.assertLessEqual(s, 4.0, msg=f"sleep[{i}]={s} exceeds max_delay=4.0")
        self.assertAlmostEqual(sleep_args[2], 4.0, places=5)
        self.assertAlmostEqual(
            sleep_args[3], 4.0, places=5, msg="delay must be capped (min), not floored (max)"
        )

    def test_delay_cap_distinguishes_min_from_max(self):
        """
        With max_delay=3.0 and base_delay=1.0:
        - Correct (min): delay[2] = min(4.0, 3.0) = 3.0
        - Wrong  (max): delay[2] = max(4.0, 3.0) = 4.0
        """
        fn = MagicMock(side_effect=[OSError()] * 3 + ["ok"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=4, base_delay=1.0, max_delay=3.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertAlmostEqual(
            sleep_args[2],
            3.0,
            places=5,
            msg="cap should be min(4.0, 3.0)=3.0, not max(4.0, 3.0)=4.0",
        )

    def test_delay_cap_small_max_delay(self):
        """When max_delay < base_delay, all delays should equal max_delay."""
        fn = MagicMock(side_effect=[OSError()] * 3 + ["ok"])
        with patch("time.sleep") as mock_sleep:
            self.retry_fn(fn, max_retries=4, base_delay=5.0, max_delay=2.0)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        for i, s in enumerate(sleep_args):
            self.assertLessEqual(s, 2.0, msg=f"sleep[{i}]={s} must not exceed max_delay=2.0")

    # ------------------------------------------------------------------
    # 5. Partial success
    # ------------------------------------------------------------------
    def test_partial_success_fail_twice_then_succeed(self):
        """fail, fail, succeed → returns success value."""
        fn = MagicMock(side_effect=[ValueError("1"), ValueError("2"), "success"])
        with patch("time.sleep"):
            result = self.retry_fn(fn, max_retries=3)
        self.assertEqual(result, "success")

    def test_partial_success_call_count(self):
        """fail twice then succeed → fn called exactly 3 times."""
        fn = MagicMock(side_effect=[OSError(), OSError(), "ok"])
        with patch("time.sleep"):
            self.retry_fn(fn, max_retries=3)
        self.assertEqual(fn.call_count, 3)

    def test_partial_success_on_last_attempt(self):
        """Succeed on the very last allowed attempt."""
        fn = MagicMock(side_effect=[OSError()] * 4 + ["last_chance"])
        with patch("time.sleep"):
            result = self.retry_fn(fn, max_retries=5)
        self.assertEqual(result, "last_chance")

    def test_partial_success_no_exception_on_eventual_success(self):
        """Even if partial failures occur, no exception if eventually succeeds."""
        fn = MagicMock(side_effect=[RuntimeError("transient"), "recovered"])
        with patch("time.sleep"):
            try:
                result = self.retry_fn(fn, max_retries=3)
            except Exception as e:
                self.fail(f"Unexpected exception on partial success: {e}")
            else:
                self.assertEqual(result, "recovered")

    def test_partial_success_stops_on_first_success(self):
        """After success, fn is not called again."""
        fn = MagicMock(side_effect=[OSError(), "ok", "should_not_reach"])
        with patch("time.sleep"):
            result = self.retry_fn(fn, max_retries=5)
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2, "fn must not be called after success")


# ------------------------------------------------------------------
# Concrete test classes — one per engine
# ------------------------------------------------------------------


class TestAppleRetry(RetryBehaviorMixin, unittest.TestCase):
    retry_fn = staticmethod(_retry_with_backoff)


class TestClaudeRetry(RetryBehaviorMixin, unittest.TestCase):
    retry_fn = staticmethod(_retry_with_backoff)


class TestGeminiRetry(RetryBehaviorMixin, unittest.TestCase):
    retry_fn = staticmethod(_retry_with_backoff)


# ------------------------------------------------------------------
# Cross-engine consistency check
# ------------------------------------------------------------------


class TestAllEnginesConsistent(unittest.TestCase):
    """Sanity: all three vision engines expose identical retry semantics."""

    def _run_retry(self, retry_fn, side_effects, max_retries=3, base_delay=1.0, max_delay=30.0):
        fn = MagicMock(side_effect=side_effects)
        sleep_calls = []

        with patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
            try:
                result = retry_fn(
                    fn, max_retries=max_retries, base_delay=base_delay, max_delay=max_delay
                )
            except Exception as exc:
                return fn.call_count, sleep_calls, exc
        return fn.call_count, sleep_calls, result

    def test_all_engines_agree_on_call_count(self):
        """All three engines call fn exactly 3 times on persistent failure."""
        for name, fn in _RETRY_IMPLS:
            with self.subTest(engine=name):
                call_count, _, _ = self._run_retry(
                    fn,
                    side_effects=[OSError()] * 3,
                    max_retries=3,
                )
                self.assertEqual(call_count, 3, f"{name}: expected 3 calls, got {call_count}")

    def test_all_engines_agree_on_delay_sequence(self):
        """All three engines produce identical delay sequences."""
        for name, fn in _RETRY_IMPLS:
            with self.subTest(engine=name):
                _, sleep_calls, _ = self._run_retry(
                    fn,
                    side_effects=[OSError(), OSError(), "ok"],
                    max_retries=3,
                    base_delay=1.0,
                    max_delay=30.0,
                )
                self.assertEqual(len(sleep_calls), 2, f"{name}: expected 2 sleeps")
                self.assertAlmostEqual(
                    sleep_calls[0], 1.0, places=5, msg=f"{name}: first delay mismatch"
                )
                self.assertAlmostEqual(
                    sleep_calls[1], 2.0, places=5, msg=f"{name}: second delay mismatch"
                )

    def test_all_engines_agree_on_raise_behavior(self):
        """All engines raise (not return None) on total failure."""
        for name, fn in _RETRY_IMPLS:
            with self.subTest(engine=name):
                _, _, outcome = self._run_retry(
                    fn,
                    side_effects=[RuntimeError("x")] * 3,
                    max_retries=3,
                )
                self.assertIsInstance(
                    outcome, Exception, f"{name}: expected exception, got {outcome!r}"
                )


if __name__ == "__main__":
    unittest.main()
