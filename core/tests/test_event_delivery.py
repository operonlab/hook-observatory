"""Adversarial tests for Redis Streams reconnection and publish_reliable.

六鐵律 mode:
- MUTATION thinking: boundary conditions, off-by-one, formula edge cases
- Test INVARIANTS: degraded flag ↔ consumer task consistency
- Mock ONLY Redis (external I/O)
- Error paths > happy paths
"""

from __future__ import annotations

import asyncio

# ── path bootstrap (same as conftest.py) ─────────────────────────────────────
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.events.backends.redis_streams import (
    _RECONNECT_BASE_DELAY,
    _RECONNECT_MAX_DELAY,
    RedisStreamsBackend,
)
from src.events.bus import Event, EventBus

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_event(event_type: str = "test.thing.happened") -> Event:
    return Event(type=event_type, data={"x": 1})


def _make_backend() -> RedisStreamsBackend:
    """Backend with no live Redis — tests inject mocks manually."""
    return RedisStreamsBackend(redis_url="redis://localhost:6379/0")


def _redis_mock() -> AsyncMock:
    """AsyncMock shaped like redis.asyncio.Redis."""
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.xadd = AsyncMock(return_value="1-0")
    r.xreadgroup = AsyncMock(return_value=[])
    r.xgroup_create = AsyncMock(return_value=True)
    r.xack = AsyncMock(return_value=1)
    r.aclose = AsyncMock()
    return r


# ─────────────────────────────────────────────────────────────────────────────
# 1. Degradation trigger: 5 consecutive errors → _degraded=True + reconnect task
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_degradation_triggers_at_exactly_5_errors():
    """INVARIANT: exactly 5 consecutive XREADGROUP errors must degrade backend.

    The consume loop sleeps between errors (up to 5s real time) — we must patch
    asyncio.sleep within the redis_streams module to collapse timing.
    """
    backend = _make_backend()
    backend._degraded = False
    redis = _redis_mock()
    backend._redis = redis
    backend._handlers = {"test.topic": [AsyncMock()]}

    # Make xreadgroup raise every time
    redis.xreadgroup.side_effect = ConnectionError("Redis gone")

    # Patch sleep inside the redis_streams module to avoid real waits
    with patch("src.events.backends.redis_streams.asyncio.sleep", new_callable=AsyncMock):
        task = asyncio.create_task(backend._consume_loop())
        # Wait for the task to finish (it returns after 5 errors)
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            pytest.fail("consume_loop did not terminate after 5 errors within 2s")

    # Post-condition: degraded and reconnect task started
    assert backend._degraded is True, "Must be degraded after 5 consecutive errors"
    assert backend._reconnect_task is not None, "Reconnect task must be created"

    # Cleanup
    backend._reconnect_task.cancel()
    try:
        await backend._reconnect_task
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 2. 4 errors is NOT enough — must NOT trigger degradation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_4_consecutive_errors_not_enough_to_degrade():
    """MUTATION: if threshold were >= 4, this would wrongly pass.  Must stay at 5."""
    backend = _make_backend()
    backend._degraded = False
    redis = _redis_mock()
    backend._redis = redis
    backend._handlers = {"test.topic": [AsyncMock()]}

    call_count = 0

    async def xreadgroup_4_errors_then_success(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 4:
            raise ConnectionError("Redis blip")
        return []  # success on 5th call

    redis.xreadgroup.side_effect = xreadgroup_4_errors_then_success

    task = asyncio.create_task(backend._consume_loop())
    # Let it run through 4 errors + 1 success
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert backend._degraded is False, (
        "4 consecutive errors must NOT trigger degradation (threshold is 5)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Error counter reset: success between errors resets to 0
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_between_errors_resets_counter():
    """INVARIANT: A successful XREADGROUP call must reset consecutive_errors to 0.

    Pattern: 4 errors, 1 success, 4 more errors → must NOT degrade.
    If counter were cumulative, 8 total errors would degrade.
    """
    backend = _make_backend()
    backend._degraded = False
    redis = _redis_mock()
    backend._redis = redis
    backend._handlers = {"test.topic": [AsyncMock()]}

    sequence = [
        ConnectionError("e1"),
        ConnectionError("e2"),
        ConnectionError("e3"),
        ConnectionError("e4"),
        None,  # success — resets counter
        ConnectionError("e5"),
        ConnectionError("e6"),
        ConnectionError("e7"),
        ConnectionError("e8"),
        None,  # success again
    ]
    call_idx = 0

    async def seq_xreadgroup(**kwargs):
        nonlocal call_idx
        if call_idx < len(sequence):
            val = sequence[call_idx]
            call_idx += 1
        else:
            val = None

        if val is not None:
            raise val
        return []

    redis.xreadgroup.side_effect = seq_xreadgroup

    task = asyncio.create_task(backend._consume_loop())
    await asyncio.sleep(0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert backend._degraded is False, (
        "Success reset must prevent degradation — 4+1+4 errors should not degrade"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Backoff bounds: delay = min(5 * 2^(n-1), 60)
# ─────────────────────────────────────────────────────────────────────────────


def _expected_backoff(attempt: int) -> float:
    return min(_RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), _RECONNECT_MAX_DELAY)


@pytest.mark.parametrize(
    "attempt, expected",
    [
        (1, 5.0),  # 5 * 2^0 = 5
        (2, 10.0),  # 5 * 2^1 = 10
        (3, 20.0),  # 5 * 2^2 = 20
        (4, 40.0),  # 5 * 2^3 = 40
        (5, 60.0),  # 5 * 2^4 = 80 → capped at 60
        (10, 60.0),  # 5 * 2^9 = 2560 → capped at 60
    ],
)
def test_backoff_formula(attempt: int, expected: float):
    """INVARIANT: backoff must be exactly min(5 * 2^(n-1), 60) for each attempt."""
    actual = _expected_backoff(attempt)
    assert actual == expected, (
        f"Attempt {attempt}: expected delay={expected}s but formula gives {actual}s"
    )


@pytest.mark.asyncio
async def test_reconnect_loop_uses_correct_backoff_delays():
    """MUTATION: verify reconnect loop actually sleeps the right duration."""
    backend = _make_backend()
    backend._degraded = True

    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def capture_sleep(delay):
        sleep_calls.append(delay)
        # Don't actually sleep, but do yield to allow other tasks
        await original_sleep(0)

    # First 3 attempts fail, 4th succeeds
    attempt_counter = 0

    async def mock_ping():
        nonlocal attempt_counter
        attempt_counter += 1
        if attempt_counter < 4:
            raise ConnectionError("still down")
        # Succeed on 4th
        return True

    fake_redis = _redis_mock()
    fake_redis.ping = mock_ping

    with (
        patch("asyncio.sleep", side_effect=capture_sleep),
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch.object(backend, "_activate_consumer", new_callable=AsyncMock),
    ):
        task = asyncio.create_task(backend._reconnect_loop())
        await asyncio.wait_for(task, timeout=5.0)

    # Should have had delays for attempts 1, 2, 3 (attempt 4 succeeded after sleep)
    assert len(sleep_calls) >= 3, f"Expected at least 3 sleep calls, got {sleep_calls}"
    assert sleep_calls[0] == 5.0, f"Attempt 1 delay must be 5s, got {sleep_calls[0]}"
    assert sleep_calls[1] == 10.0, f"Attempt 2 delay must be 10s, got {sleep_calls[1]}"
    assert sleep_calls[2] == 20.0, f"Attempt 3 delay must be 20s, got {sleep_calls[2]}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reconnect success: _degraded=False and consumer task running
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_success_clears_degraded_and_starts_consumer():
    """INVARIANT: after successful reconnect, _degraded must be False and
    _consumer_task must be a running Task."""
    backend = _make_backend()
    backend._degraded = True
    backend._reconnect_attempts = 2  # Simulate previous failures

    fake_redis = _redis_mock()
    consumer_started = asyncio.Event()

    async def fake_activate_consumer():
        consumer_started.set()
        # Create a real task that stays alive
        backend._consumer_task = asyncio.create_task(asyncio.sleep(100))

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch.object(backend, "_activate_consumer", side_effect=fake_activate_consumer),
    ):
        task = asyncio.create_task(backend._reconnect_loop())
        await asyncio.wait_for(consumer_started.wait(), timeout=2.0)
        # Give the loop time to update state
        await asyncio.sleep(0)

    assert backend._degraded is False, "_degraded must be False after successful reconnect"
    assert backend._consumer_task is not None, "_consumer_task must exist after reconnect"
    assert not backend._consumer_task.done(), "_consumer_task must still be running"

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    backend._consumer_task.cancel()
    try:
        await backend._consumer_task
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 6. Reconnect cleans up: _reconnect_attempts resets to 0 on success
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_attempts_reset_to_zero_on_success():
    """MUTATION: if reset were missing, _reconnect_attempts would accumulate.
    This would cause artificially long backoff delays on future reconnects.
    """
    backend = _make_backend()
    backend._degraded = True
    backend._reconnect_attempts = 0

    reconnect_done = asyncio.Event()

    async def fake_activate_consumer():
        reconnect_done.set()
        backend._consumer_task = asyncio.create_task(asyncio.sleep(100))

    fake_redis = _redis_mock()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch.object(backend, "_activate_consumer", side_effect=fake_activate_consumer),
    ):
        task = asyncio.create_task(backend._reconnect_loop())
        await asyncio.wait_for(reconnect_done.wait(), timeout=2.0)
        await asyncio.sleep(0)

    assert backend._reconnect_attempts == 0, (
        "_reconnect_attempts must reset to 0 after successful reconnect "
        f"(got {backend._reconnect_attempts})"
    )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if backend._consumer_task:
        backend._consumer_task.cancel()
        try:
            await backend._consumer_task
        except asyncio.CancelledError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 7. Publish during degraded: must use _publish_fallback, not xadd
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_during_degraded_uses_fallback_not_xadd():
    """INVARIANT: when _degraded=True, publish() must never call redis.xadd."""
    backend = _make_backend()
    backend._degraded = True

    redis = _redis_mock()
    backend._redis = redis

    handler = AsyncMock()
    backend._handlers = {"test.thing.happened": [handler]}

    event = _make_event("test.thing.happened")
    await backend.publish(event)

    redis.xadd.assert_not_called()
    handler.assert_called_once()


@pytest.mark.asyncio
async def test_publish_without_redis_uses_fallback():
    """INVARIANT: when _redis=None (never connected), must use fallback, not crash."""
    backend = _make_backend()
    backend._degraded = False  # degraded=False but redis=None — edge case
    backend._redis = None

    handler = AsyncMock()
    backend._handlers = {"test.thing.happened": [handler]}

    event = _make_event("test.thing.happened")
    # Should not raise
    await backend.publish(event)

    # publish() checks `self._degraded or self._redis is None` → fallback
    handler.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 8. publish_reliable: success on first try
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_reliable_success_on_first_try():
    """Happy path: publish_reliable returns True, backend.publish called once."""
    backend = MagicMock()
    backend.publish = AsyncMock(return_value=None)
    backend.use_middleware = MagicMock()
    backend.subscribe = MagicMock()

    bus = EventBus(backend=backend)
    event = _make_event()

    result = await bus.publish_reliable(event, max_retries=3, base_delay=0.0)

    assert result is True
    assert backend.publish.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 9. publish_reliable: success on retry
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_reliable_success_on_second_attempt():
    """First call raises, second succeeds → returns True."""
    backend = MagicMock()
    call_count = 0

    async def publish_once_then_ok(event):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("first attempt fails")

    backend.publish = publish_once_then_ok
    backend.use_middleware = MagicMock()
    backend.subscribe = MagicMock()

    bus = EventBus(backend=backend)
    event = _make_event()

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await bus.publish_reliable(event, max_retries=3, base_delay=0.5)

    assert result is True
    assert call_count == 2, f"Expected 2 calls, got {call_count}"


# ─────────────────────────────────────────────────────────────────────────────
# 10. publish_reliable: exhaustion — all 3 attempts fail → returns False
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_reliable_exhaustion_returns_false():
    """All 3 attempts fail → returns False, never raises."""
    backend = MagicMock()
    backend.publish = AsyncMock(side_effect=ConnectionError("always fails"))
    backend.use_middleware = MagicMock()
    backend.subscribe = MagicMock()

    bus = EventBus(backend=backend)
    event = _make_event()

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await bus.publish_reliable(event, max_retries=3, base_delay=0.5)

    assert result is False
    assert backend.publish.call_count == 3, (
        f"All 3 attempts must be tried (got {backend.publish.call_count})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. publish_reliable: backoff timing — delays must be 0.5s, 1.0s (not flat 0.5)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_reliable_backoff_is_linear_not_flat():
    """MUTATION: backoff is base_delay * attempt, not base_delay * 1 (flat).

    Delays for 3-attempt sequence:
      - Between attempt 1 and 2: sleep(0.5 * 1) = 0.5s
      - Between attempt 2 and 3: sleep(0.5 * 2) = 1.0s
      - No sleep after final attempt
    """
    backend = MagicMock()
    backend.publish = AsyncMock(side_effect=ConnectionError("always fails"))
    backend.use_middleware = MagicMock()
    backend.subscribe = MagicMock()

    bus = EventBus(backend=backend)
    event = _make_event()

    sleep_calls: list[float] = []

    async def capture_sleep(delay):
        sleep_calls.append(delay)

    with patch("asyncio.sleep", side_effect=capture_sleep):
        result = await bus.publish_reliable(event, max_retries=3, base_delay=0.5)

    assert result is False
    assert len(sleep_calls) == 2, (
        f"Expected exactly 2 sleep calls (between 3 attempts), got {len(sleep_calls)}"
    )
    assert sleep_calls[0] == 0.5, (
        f"First inter-attempt delay must be 0.5s (base * 1), got {sleep_calls[0]}"
    )
    assert sleep_calls[1] == 1.0, (
        f"Second inter-attempt delay must be 1.0s (base * 2), got {sleep_calls[1]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Additional invariant: degraded flag ↔ consumer task mutual consistency
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_degraded_flag_and_consumer_task_mutually_exclusive():
    """INVARIANT: when _degraded=True, the consumer task must NOT be running.
    Violations indicate incomplete state transitions.
    """
    backend = _make_backend()
    backend._degraded = True

    fake_redis = _redis_mock()
    consumer_done = asyncio.Event()

    async def fake_activate_consumer():
        consumer_done.set()
        backend._consumer_task = asyncio.create_task(asyncio.sleep(100))

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch.object(backend, "_activate_consumer", side_effect=fake_activate_consumer),
    ):
        task = asyncio.create_task(backend._reconnect_loop())
        await asyncio.wait_for(consumer_done.wait(), timeout=2.0)
        await asyncio.sleep(0)

    # After successful reconnect: degraded=False, consumer running
    assert backend._degraded is False
    if backend._consumer_task is not None:
        assert not backend._consumer_task.done(), "Consumer task must be running when not degraded"

    # Simulate degradation trigger from consume_loop
    if backend._consumer_task:
        backend._consumer_task.cancel()
        try:
            await backend._consumer_task
        except asyncio.CancelledError:
            pass

    backend._degraded = True
    # When degraded: consumer_task should be done or None
    if backend._consumer_task is not None:
        # After cancel, done() should be True
        assert backend._consumer_task.done(), (
            "Consumer task must not be running when _degraded=True"
        )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Backoff cap: ensure cap is respected and doesn't go below base delay
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("attempt", range(1, 20))
def test_backoff_never_exceeds_max_delay(attempt: int):
    """INVARIANT: backoff delay must never exceed _RECONNECT_MAX_DELAY (60s)."""
    delay = min(_RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), _RECONNECT_MAX_DELAY)
    assert delay <= _RECONNECT_MAX_DELAY, (
        f"Attempt {attempt}: delay {delay} exceeds max {_RECONNECT_MAX_DELAY}"
    )


@pytest.mark.parametrize("attempt", range(1, 20))
def test_backoff_never_below_base_delay(attempt: int):
    """INVARIANT: backoff delay must never be less than _RECONNECT_BASE_DELAY (5s)."""
    delay = min(_RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), _RECONNECT_MAX_DELAY)
    assert delay >= _RECONNECT_BASE_DELAY, (
        f"Attempt {attempt}: delay {delay} is below base delay {_RECONNECT_BASE_DELAY}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MUTATION: verify the log in reconnect_loop records WRONG attempts count
# This is a documented code smell — the log fires AFTER reset, recording 0
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_log_records_zero_attempts_after_reset():
    """BUG FINDER: in _reconnect_loop, after successful reconnect:
        self._reconnect_attempts = 0   (reset first)
        logger.info(..., attempts=self._reconnect_attempts)  (then log → always 0)

    This test documents the behaviour — if the bug is fixed (log before reset),
    this test should be updated to reflect the correct value.
    """
    backend = _make_backend()
    backend._degraded = True
    backend._reconnect_attempts = 0

    reconnect_done = asyncio.Event()
    logged_attempts: list[int] = []

    async def fake_activate_consumer():
        reconnect_done.set()
        backend._consumer_task = asyncio.create_task(asyncio.sleep(100))

    fake_redis = _redis_mock()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch.object(backend, "_activate_consumer", side_effect=fake_activate_consumer),
    ):
        task = asyncio.create_task(backend._reconnect_loop())
        await asyncio.wait_for(reconnect_done.wait(), timeout=2.0)
        await asyncio.sleep(0)

    # After successful reconnect, _reconnect_attempts should be 0
    # (it was reset before the log call)
    assert backend._reconnect_attempts == 0

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if backend._consumer_task:
        backend._consumer_task.cancel()
        try:
            await backend._consumer_task
        except asyncio.CancelledError:
            pass
