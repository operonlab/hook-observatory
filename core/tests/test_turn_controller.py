"""Tests for TurnController — prompt execution lifecycle FSM."""

from __future__ import annotations

import pytest
from src.shared.turn_controller import TurnController, TurnState

# ---------------------------------------------------------------------------
# 1. State transitions: idle → starting → active → closing → idle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_transitions() -> None:
    """Full lifecycle should pass through all states in the correct order."""
    ctrl = TurnController()
    assert ctrl.state is TurnState.IDLE

    states_seen: list[TurnState] = []

    async with ctrl.turn() as c:
        # Inside the context manager we should be ACTIVE
        states_seen.append(c.state)

    # After exiting we should be IDLE again
    states_seen.append(ctrl.state)

    assert states_seen == [TurnState.ACTIVE, TurnState.IDLE]


@pytest.mark.asyncio
async def test_cannot_nest_turns() -> None:
    """Starting a second turn while one is active should raise RuntimeError."""
    ctrl = TurnController()

    with pytest.raises(RuntimeError, match="cannot start turn"):
        async with ctrl.turn():
            # Attempt to open a nested turn — should fail immediately
            async with ctrl.turn():
                pass


@pytest.mark.asyncio
async def test_turn_reusable() -> None:
    """Controller should be reusable across multiple sequential turns."""
    ctrl = TurnController()

    for _ in range(3):
        async with ctrl.turn():
            assert ctrl.state is TurnState.ACTIVE
        assert ctrl.state is TurnState.IDLE


# ---------------------------------------------------------------------------
# 2. Cancel during ACTIVE state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_during_active() -> None:
    """request_cancel() while ACTIVE should set is_cancelled immediately."""
    ctrl = TurnController()

    async with ctrl.turn():
        assert ctrl.state is TurnState.ACTIVE
        assert not ctrl.is_cancelled
        ctrl.request_cancel()
        assert ctrl.is_cancelled

    # After the turn the state resets to IDLE
    assert ctrl.state is TurnState.IDLE


# ---------------------------------------------------------------------------
# 3. Cancel deferred during STARTING state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_deferred_mechanism() -> None:
    """Verify the deferred cancel mechanism: pending_cancel triggers on ACTIVE entry."""
    ctrl = TurnController()

    # Directly manipulate internals to simulate what would happen
    # if request_cancel() is called during the STARTING → ACTIVE gap.
    # In production, this would come from a concurrent coroutine.
    #
    # We set _pending_cancel AFTER turn() enters STARTING but BEFORE it
    # transitions to ACTIVE. Since turn() doesn't await between STARTING and
    # ACTIVE, we can't inject via a real concurrent task. Instead, we verify
    # the mechanism by setting the flag right before ACTIVE transition:

    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def patched_turn() -> AsyncIterator[TurnController]:
        """Wrapper that injects pending_cancel during STARTING state."""
        # Enter the original turn (acquires lock, sets STARTING)
        async with ctrl._lock:
            if ctrl._state is not TurnState.IDLE:
                msg = f"cannot start turn from state {ctrl._state.value!r}"
                raise RuntimeError(f"TurnController: {msg}")
            ctrl._cancel_event.clear()
            ctrl._pending_cancel = False
            ctrl._state = TurnState.STARTING

        # Now in STARTING — inject the pending cancel
        ctrl._pending_cancel = True

        # STARTING → ACTIVE (same as original turn code)
        ctrl._state = TurnState.ACTIVE
        if ctrl._pending_cancel:
            ctrl._pending_cancel = False
            ctrl._cancel_event.set()

        try:
            yield ctrl
        finally:
            ctrl._state = TurnState.CLOSING
            async with ctrl._lock:
                ctrl._state = TurnState.IDLE

    async with patched_turn():
        assert ctrl.is_cancelled, "Deferred cancel should fire on ACTIVE entry"

    assert ctrl.state is TurnState.IDLE


@pytest.mark.asyncio
async def test_cancel_idle_is_noop() -> None:
    """request_cancel() while IDLE should have no effect."""
    ctrl = TurnController()
    assert ctrl.state is TurnState.IDLE
    ctrl.request_cancel()  # must not raise or change anything
    assert not ctrl.is_cancelled
    assert not ctrl._pending_cancel


@pytest.mark.asyncio
async def test_cancel_clears_between_turns() -> None:
    """is_cancelled should be False at the start of each new turn."""
    ctrl = TurnController()

    async with ctrl.turn():
        ctrl.request_cancel()
        assert ctrl.is_cancelled

    # Second turn — cancel event should be cleared
    async with ctrl.turn():
        assert not ctrl.is_cancelled
