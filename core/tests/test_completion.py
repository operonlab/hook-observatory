"""Adversarial tests for TaskCompletion — designed to BREAK code, not confirm it.

Testing Strategy (六鐵律):
  1. Mutation thinking: every branch has a mutation test that kills off-by-one changes
  2. Invariants over fixed I/O: idempotency, monotonicity, exactly-once semantics
  3. No mocks — TaskCompletion is pure async; Observer is a thin in-process stub
  4. Edge cases and error paths dominate; happy path is minimal
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shared.completion import (
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    TIMEOUT,
    CompletionRegistry,
    CompletionResult,
    TaskCompletion,
)

# ─── Helpers ────────────────────────────────────────────────────────────────


class RecordingObserver:
    """Test double — records all calls without mocking external I/O."""

    def __init__(self) -> None:
        self.nexts: list = []
        self.errors: list[Exception] = []
        self.completes: int = 0

    async def on_next(self, value) -> None:
        self.nexts.append(value)

    async def on_error(self, error: Exception) -> None:
        self.errors.append(error)

    async def on_complete(self) -> None:
        self.completes += 1


def make_tc(task_id: str = "test-task") -> TaskCompletion:
    return TaskCompletion(task_id)


# ─── 1. Resolve Idempotency ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_twice_same_result():
    """Second resolve() must be a no-op — value from first call wins."""
    tc = make_tc()
    await tc.resolve("first")
    await tc.resolve("second")  # must be ignored

    result = await tc.wait()
    assert result == "first", "Second resolve() overwrote first — idempotency broken"


@pytest.mark.asyncio
async def test_resolve_twice_status_stays_completed():
    """Status must not change after first resolve."""
    tc = make_tc()
    await tc.resolve("x")
    pre_status = tc.status
    await tc.resolve("y")
    assert tc.status == pre_status == COMPLETED


@pytest.mark.asyncio
async def test_resolve_twice_observer_notified_exactly_once():
    """Observers must receive exactly one delivery — not two.

    Mutation target: if the idempotency guard `if self.is_terminal: return`
    were removed, observers would be notified twice.
    """
    obs = RecordingObserver()
    tc = make_tc()
    tc.subscribe(obs)

    await tc.resolve("value")
    await tc.resolve("value-again")

    # Allow any pending tasks to complete
    await asyncio.sleep(0)

    assert len(obs.nexts) == 1, f"Observer.on_next called {len(obs.nexts)} times, expected 1"
    assert obs.completes == 1, f"Observer.on_complete called {obs.completes} times, expected 1"


# ─── 2. Reject Idempotency ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_after_resolve_is_noop():
    """reject() after resolve() must not change status or result.

    Mutation target: `if self.is_terminal: return` — if guard uses `not`,
    resolve would be ignored and reject would win.
    """
    tc = make_tc()
    await tc.resolve(42)
    later_error = ValueError("too late")
    await tc.reject(later_error)

    assert tc.status == COMPLETED, "reject() after resolve() changed status"
    result = await tc.wait()
    assert result == 42, "reject() after resolve() changed result value"


@pytest.mark.asyncio
async def test_resolve_after_reject_is_noop():
    """resolve() after reject() must not change status or suppress the error."""
    tc = make_tc()
    original_error = RuntimeError("original failure")
    await tc.reject(original_error)
    await tc.resolve("too late")

    assert tc.status == FAILED
    with pytest.raises(RuntimeError) as exc_info:
        await tc.wait()
    assert exc_info.value is original_error


@pytest.mark.asyncio
async def test_reject_twice_first_error_wins():
    """Second reject() must be ignored; first error instance is preserved."""
    tc = make_tc()
    first_error = ValueError("first")
    second_error = ValueError("second")
    await tc.reject(first_error)
    await tc.reject(second_error)

    with pytest.raises(ValueError) as exc_info:
        await tc.wait()
    assert exc_info.value is first_error


# ─── 3. Late Subscriber Replay ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_late_subscriber_gets_cached_resolve():
    """subscribe() AFTER resolve() must immediately replay the cached value.

    Mutation target: the `if self.is_terminal and self._result is not None`
    guard in subscribe(). If `and` becomes `or`, a pending TC with None result
    would incorrectly enter the late-replay path and crash.
    """
    tc = make_tc()
    await tc.resolve("cached-value")

    # Subscribe AFTER resolution
    obs = RecordingObserver()
    tc.subscribe(obs)

    # Late delivery is async via ensure_future — yield control
    await asyncio.sleep(0)

    assert obs.nexts == ["cached-value"], f"Late subscriber got: {obs.nexts}"
    assert obs.completes == 1


@pytest.mark.asyncio
async def test_late_subscriber_gets_cached_reject():
    """Late subscriber on a FAILED completion must receive on_error, not on_next."""
    tc = make_tc()
    err = OSError("upstream failure")
    await tc.reject(err)

    obs = RecordingObserver()
    tc.subscribe(obs)
    await asyncio.sleep(0)

    assert len(obs.nexts) == 0, "on_next called for rejected completion"
    assert len(obs.errors) == 1
    assert obs.errors[0] is err


@pytest.mark.asyncio
async def test_late_subscriber_gets_cached_timeout():
    """Late subscriber on a TIMEOUT completion must receive on_error with TimeoutError."""
    tc = make_tc()
    await tc.timeout()

    obs = RecordingObserver()
    tc.subscribe(obs)
    await asyncio.sleep(0)

    assert len(obs.errors) == 1
    assert isinstance(obs.errors[0], TimeoutError)
    assert len(obs.nexts) == 0


# ─── 4. Timeout Behavior ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_timeout_raises_timeout_error():
    """wait(timeout=N) on a never-resolved TC must raise TimeoutError.

    Mutation target: the `except TimeoutError: await self.timeout()` block.
    If `await self.timeout()` is omitted, status stays PENDING and
    `_result` is None → RuntimeError is raised instead of TimeoutError.
    """
    tc = make_tc()
    with pytest.raises(TimeoutError):
        await tc.wait(timeout=0.01)


@pytest.mark.asyncio
async def test_wait_timeout_sets_status_timeout():
    """After wait() times out, status must be TIMEOUT, not PENDING or RUNNING."""
    tc = make_tc()
    with pytest.raises(TimeoutError):
        await tc.wait(timeout=0.01)

    assert tc.status == TIMEOUT, f"Status after timeout: {tc.status!r}"
    assert tc.is_terminal


@pytest.mark.asyncio
async def test_wait_timeout_calls_self_timeout():
    """wait() timeout must delegate to self.timeout(), which notifies observers.

    Mutation target: if `await self.timeout()` is replaced with just
    `raise TimeoutError(...)`, observers will never be notified on timeout.
    """
    obs = RecordingObserver()
    tc = make_tc()
    tc.subscribe(obs)

    with pytest.raises(TimeoutError):
        await tc.wait(timeout=0.01)

    # Observer must have been notified about the timeout error
    assert len(obs.errors) == 1, "Observer not notified on timeout"
    assert isinstance(obs.errors[0], TimeoutError)


@pytest.mark.asyncio
async def test_zero_timeout_behavior():
    """wait(timeout=0) on a pending TC — must raise TimeoutError immediately.

    This tests the boundary: timeout=0 means "no patience at all".
    """
    tc = make_tc()
    with pytest.raises(TimeoutError):
        await tc.wait(timeout=0)


@pytest.mark.asyncio
async def test_wait_no_timeout_already_resolved():
    """wait() with timeout=None on an already-resolved TC must return immediately."""
    tc = make_tc()
    await tc.resolve("done")
    result = await tc.wait(timeout=None)
    assert result == "done"


# ─── 5. Concurrent wait() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_waiters_all_get_same_result():
    """Multiple coroutines awaiting wait() simultaneously must all get the same value.

    Mutation target: if `_event.set()` were replaced with `_event.wait()` in
    resolve(), or if the Event were reset after first waiter, later waiters
    would block forever.
    """
    tc = make_tc()
    results: list = []
    errors: list[Exception] = []

    async def waiter():
        try:
            v = await tc.wait()
            results.append(v)
        except Exception as e:
            errors.append(e)

    # Launch 5 waiters before resolving
    tasks = [asyncio.create_task(waiter()) for _ in range(5)]
    await asyncio.sleep(0)  # yield so waiters actually start waiting

    await tc.resolve("shared-result")
    await asyncio.gather(*tasks)

    assert errors == [], f"Some waiters raised: {errors}"
    assert len(results) == 5, f"Only {len(results)}/5 waiters received a result"
    assert all(r == "shared-result" for r in results), f"Results differ: {results}"


@pytest.mark.asyncio
async def test_concurrent_waiters_all_raise_on_reject():
    """All concurrent waiters must raise on reject — same error, not just first."""
    tc = make_tc()
    errors: list[Exception] = []

    async def waiter():
        try:
            await tc.wait()
        except Exception as e:
            errors.append(e)

    tasks = [asyncio.create_task(waiter()) for _ in range(3)]
    await asyncio.sleep(0)

    original_error = ValueError("shared failure")
    await tc.reject(original_error)
    await asyncio.gather(*tasks)

    assert len(errors) == 3
    # All waiters must raise the EXACT same error instance (re-raise, not wrap)
    assert all(e is original_error for e in errors), "Errors are not the same instance"


# ─── 6. Status Monotonicity ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_status_never_reverts_to_pending():
    """Once COMPLETED, status must never become PENDING or RUNNING.

    Mutation target: if is_terminal does not include TIMEOUT (e.g., only
    checks COMPLETED and FAILED), calling timeout() after resolve() would
    succeed and corrupt state.
    """
    tc = make_tc()
    await tc.resolve("ok")
    assert tc.status == COMPLETED
    assert tc.is_terminal

    # None of these should change status
    await tc.reject(ValueError("no"))
    await tc.timeout()
    tc.mark_running()  # must not revert to RUNNING

    assert tc.status == COMPLETED


@pytest.mark.asyncio
async def test_timeout_status_is_terminal():
    """TIMEOUT must be recognized as terminal by is_terminal.

    Mutation target: if TIMEOUT were removed from the is_terminal tuple check,
    timeout() would loop (it calls `if self.is_terminal: return`, which would
    be False, so it would keep trying — but actually it would not loop since
    status is set first... however subsequent calls would re-enter).
    """
    tc = make_tc()
    await tc.timeout()
    assert tc.is_terminal
    assert tc.status == TIMEOUT


@pytest.mark.asyncio
async def test_mark_running_only_from_pending():
    """mark_running() must be a no-op if status is already RUNNING or terminal."""
    tc = make_tc()
    tc.mark_running()
    assert tc.status == RUNNING

    # Second mark_running must not crash (guard: status == PENDING)
    tc.mark_running()
    assert tc.status == RUNNING

    await tc.resolve("x")
    tc.mark_running()  # terminal — must not change status
    assert tc.status == COMPLETED


@pytest.mark.asyncio
async def test_status_transitions_are_monotonic():
    """Status must only increase along the lifecycle: PENDING → RUNNING → terminal.

    No backward transitions are allowed: terminal → PENDING is forbidden.
    """
    tc = make_tc()
    seen_statuses = [tc.status]

    tc.mark_running()
    seen_statuses.append(tc.status)
    await tc.resolve("final")
    seen_statuses.append(tc.status)

    terminal_statuses = {COMPLETED, FAILED, TIMEOUT}
    assert seen_statuses == [PENDING, RUNNING, COMPLETED]

    # Once terminal, status is frozen
    pre = tc.status
    await tc.reject(Exception("ignored"))
    assert tc.status == pre


# ─── 7. Observer Cleanup ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observers_cleared_after_resolve():
    """After resolve(), _observers list must be empty (prevent memory leak).

    Mutation target: if `_observers.clear()` in `_notify_observers()` is
    removed, the list retains references and grows unboundedly.
    """
    tc = make_tc()
    for _ in range(5):
        tc.subscribe(RecordingObserver())

    assert len(tc._observers) == 5

    await tc.resolve("done")
    await asyncio.sleep(0)

    assert len(tc._observers) == 0, (
        f"Memory leak: {len(tc._observers)} observers still referenced after resolve"
    )


@pytest.mark.asyncio
async def test_observers_cleared_after_reject():
    """After reject(), _observers list must also be empty."""
    tc = make_tc()
    for _ in range(3):
        tc.subscribe(RecordingObserver())

    await tc.reject(RuntimeError("fail"))
    await asyncio.sleep(0)

    assert len(tc._observers) == 0


@pytest.mark.asyncio
async def test_unsubscribe_removes_observer_before_resolve():
    """Unsubscribed observer must NOT receive notifications.

    Mutation target: the lambda in subscribe() — if observer is not actually
    removed from _observers on unsubscribe(), it will still receive events.
    """
    tc = make_tc()
    obs = RecordingObserver()
    sub = tc.subscribe(obs)
    sub.unsubscribe()

    await tc.resolve("value")
    await asyncio.sleep(0)

    assert obs.nexts == [], "Unsubscribed observer still received on_next"
    assert obs.completes == 0, "Unsubscribed observer still received on_complete"


# ─── 8. CompletionRegistry ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_register_and_get():
    """Registered TC must be retrievable by task_id."""
    reg = CompletionRegistry()
    tc = make_tc("task-abc")
    reg.register(tc)
    assert reg.get("task-abc") is tc


def test_registry_get_missing_returns_none():
    """get() on unknown task_id must return None, not raise."""
    reg = CompletionRegistry()
    assert reg.get("nonexistent") is None


def test_registry_remove_nonexistent_is_noop():
    """remove() on unknown task_id must not raise KeyError."""
    reg = CompletionRegistry()
    reg.remove("ghost")  # must not raise


def test_registry_remove_existing():
    """After remove(), get() must return None."""
    reg = CompletionRegistry()
    tc = make_tc("task-del")
    reg.register(tc)
    reg.remove("task-del")
    assert reg.get("task-del") is None


@pytest.mark.asyncio
async def test_registry_cleanup_terminal_only_removes_terminal():
    """cleanup_terminal() must remove ONLY terminal TCs, leave pending ones intact."""
    reg = CompletionRegistry()
    pending_tc = make_tc("pending")
    running_tc = make_tc("running")
    running_tc.mark_running()
    done_tc = make_tc("done")
    failed_tc = make_tc("failed")

    await done_tc.resolve("ok")
    await failed_tc.reject(ValueError("err"))

    reg.register(pending_tc)
    reg.register(running_tc)
    reg.register(done_tc)
    reg.register(failed_tc)

    removed = reg.cleanup_terminal()

    assert removed == 2, f"Expected 2 removed, got {removed}"
    assert reg.get("pending") is pending_tc, "Pending TC incorrectly removed"
    assert reg.get("running") is running_tc, "Running TC incorrectly removed"
    assert reg.get("done") is None, "Completed TC NOT removed"
    assert reg.get("failed") is None, "Failed TC NOT removed"


@pytest.mark.asyncio
async def test_registry_cleanup_terminal_returns_count():
    """cleanup_terminal() return value must equal the actual number of items removed.

    Mutation target: if `return len(to_remove)` were replaced with
    `return len(self._completions)`, count would be wrong.
    """
    reg = CompletionRegistry()
    for i in range(4):
        tc = make_tc(f"task-{i}")
        reg.register(tc)
        if i < 3:
            await tc.resolve(i)

    removed = reg.cleanup_terminal()
    assert removed == 3, f"Expected 3, got {removed}"


@pytest.mark.asyncio
async def test_registry_active_count_excludes_terminal():
    """active_count must only count non-terminal TCs."""
    reg = CompletionRegistry()
    tc1 = make_tc("a")
    tc2 = make_tc("b")
    tc3 = make_tc("c")
    reg.register(tc1)
    reg.register(tc2)
    reg.register(tc3)
    await tc1.resolve("done")

    assert reg.active_count == 2


def test_registry_len_counts_all_including_terminal():
    """__len__ must count ALL registered TCs (pending + terminal)."""
    reg = CompletionRegistry()
    assert len(reg) == 0
    reg.register(make_tc("a"))
    reg.register(make_tc("b"))
    assert len(reg) == 2


@pytest.mark.asyncio
async def test_registry_register_overwrites_same_id():
    """Registering a new TC with the same task_id must overwrite the old one.

    This is a boundary: the registry uses task_id as key. If two TCs share
    the same ID, the last-registered one wins.
    """
    reg = CompletionRegistry()
    tc1 = make_tc("shared-id")
    tc2 = make_tc("shared-id")
    reg.register(tc1)
    reg.register(tc2)
    assert reg.get("shared-id") is tc2


# ─── 9. Zero-Timeout Edge Case ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_timeout_on_already_resolved_does_not_raise():
    """wait(timeout=0) on an already-completed TC must return immediately without raising.

    The `if not self.is_terminal` guard in wait() should bypass the timeout
    path entirely for already-terminal TCs.
    """
    tc = make_tc()
    await tc.resolve("instant")
    # Must NOT raise even with timeout=0, because TC is already terminal
    result = await tc.wait(timeout=0)
    assert result == "instant"


@pytest.mark.asyncio
async def test_zero_timeout_marks_as_timeout_and_raises():
    """wait(timeout=0) on a pending TC must mark as TIMEOUT and raise TimeoutError."""
    tc = make_tc()
    with pytest.raises(TimeoutError):
        await tc.wait(timeout=0)

    assert tc.status == TIMEOUT
    assert tc.is_terminal


# ─── 10. Error Propagation — Exact Instance ─────────────────────────────────


@pytest.mark.asyncio
async def test_reject_propagates_exact_error_instance():
    """wait() must re-raise the EXACT same error instance passed to reject().

    Mutation target: if `raise self._result.error` were replaced with
    `raise type(self._result.error)(str(self._result.error))`, the identity
    check would fail, hiding the original traceback and context.
    """
    tc = make_tc()
    original = ValueError("exact instance check")
    await tc.reject(original)

    with pytest.raises(ValueError) as exc_info:
        await tc.wait()

    assert exc_info.value is original, (
        "wait() raised a copy of the error, not the original instance — "
        "original traceback and context are lost"
    )


@pytest.mark.asyncio
async def test_reject_with_chained_exception_preserves_chain():
    """Chained exceptions (__cause__) must be preserved when re-raised."""
    tc = make_tc()
    cause = OSError("disk read failed")
    wrapped = RuntimeError("processing failed")
    wrapped.__cause__ = cause
    await tc.reject(wrapped)

    with pytest.raises(RuntimeError) as exc_info:
        await tc.wait()

    assert exc_info.value.__cause__ is cause


@pytest.mark.asyncio
async def test_reject_arbitrary_exception_type():
    """reject() must handle any Exception subclass, not just ValueError/RuntimeError."""

    class CustomDomainError(Exception):
        def __init__(self, code: int, msg: str):
            super().__init__(msg)
            self.code = code

    tc = make_tc()
    err = CustomDomainError(404, "not found")
    await tc.reject(err)

    with pytest.raises(CustomDomainError) as exc_info:
        await tc.wait()

    assert exc_info.value is err
    assert exc_info.value.code == 404


# ─── Bonus: CompletionResult invariants ─────────────────────────────────────


def test_completion_result_ok_when_no_error():
    """`ok` must be True when error is None."""
    r = CompletionResult(value=42, error=None)
    assert r.ok is True


def test_completion_result_not_ok_when_error():
    """`ok` must be False when error is set — even if value is also set.

    Mutation target: if `ok` used `value is not None` instead of
    `error is None`, a result with value=None and error=... would appear ok.
    """
    r = CompletionResult(value="something", error=ValueError("oops"))
    assert r.ok is False


def test_completion_result_ok_with_none_value():
    """`ok` must be True even when value is None (falsy), as long as error is None."""
    r = CompletionResult(value=None, error=None)
    assert r.ok is True


# ─── Bonus: Timeout TC is re-raise safe ─────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_after_manual_timeout_raises_timeout_error():
    """After manually calling tc.timeout(), subsequent wait() must raise TimeoutError."""
    tc = make_tc()
    await tc.timeout()

    with pytest.raises(TimeoutError):
        await tc.wait()


@pytest.mark.asyncio
async def test_multiple_wait_calls_after_resolve_are_idempotent():
    """Multiple sequential wait() calls after resolve must all return the same value."""
    tc = make_tc()
    await tc.resolve("stable")

    results = []
    for _ in range(3):
        results.append(await tc.wait())

    assert results == ["stable", "stable", "stable"]


@pytest.mark.asyncio
async def test_multiple_wait_calls_after_reject_all_raise():
    """Multiple sequential wait() calls after reject must all raise the same error."""
    tc = make_tc()
    err = RuntimeError("persistent failure")
    await tc.reject(err)

    for _ in range(3):
        with pytest.raises(RuntimeError) as exc_info:
            await tc.wait()
        assert exc_info.value is err
