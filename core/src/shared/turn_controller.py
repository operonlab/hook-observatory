"""Turn Controller FSM — prompt execution lifecycle manager.

Inspired by acpx's QueueOwnerTurnController.
States: idle → starting → active → closing → idle

Usage:
    ctrl = TurnController()
    async with ctrl.turn():
        # State: active
        result = await execute_prompt(...)
    # State: idle

    # Cancel is deferred until active:
    ctrl.request_cancel()  # If starting, waits. If active, cancels immediately.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum


class TurnState(Enum):
    """Lifecycle states of a single prompt execution turn."""

    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    CLOSING = "closing"


class TurnController:
    """FSM that manages prompt execution lifecycle with deferred cancel support.

    Cancel semantics:
    - IDLE     → no-op (nothing running)
    - STARTING → deferred: applied as soon as ACTIVE is entered
    - ACTIVE   → immediate: sets the cancel event
    - CLOSING  → no-op (already winding down)
    """

    def __init__(self) -> None:
        self._state = TurnState.IDLE
        self._lock = asyncio.Lock()
        self._cancel_event = asyncio.Event()
        self._pending_cancel = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def is_cancelled(self) -> bool:
        """True once a cancel has been applied (event is set)."""
        return self._cancel_event.is_set()

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def request_cancel(self) -> None:
        """Request cancellation of the current turn.

        If STARTING: queues a pending cancel to be applied on ACTIVE entry.
        If ACTIVE:   fires the cancel event immediately.
        Otherwise:   no-op.
        """
        if self._state is TurnState.IDLE or self._state is TurnState.CLOSING:
            return
        if self._state is TurnState.STARTING:
            self._pending_cancel = True
        elif self._state is TurnState.ACTIVE:
            self._cancel_event.set()

    # ------------------------------------------------------------------
    # Turn context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[TurnController]:
        """Run one prompt turn through the full IDLE→STARTING→ACTIVE→CLOSING→IDLE cycle.

        Yields self so callers can inspect ``is_cancelled`` during execution.

        Raises RuntimeError if a turn is already in progress.
        """
        async with self._lock:
            if self._state is not TurnState.IDLE:
                raise RuntimeError(
                    f"TurnController: cannot start turn from state {self._state.value!r}"
                )
            self._cancel_event.clear()
            self._pending_cancel = False
            self._state = TurnState.STARTING

        # STARTING → ACTIVE
        # Apply any cancel that arrived while we were starting up.
        self._state = TurnState.ACTIVE
        if self._pending_cancel:
            self._pending_cancel = False
            self._cancel_event.set()

        try:
            yield self
        finally:
            # ACTIVE → CLOSING → IDLE
            self._state = TurnState.CLOSING
            async with self._lock:
                self._state = TurnState.IDLE
