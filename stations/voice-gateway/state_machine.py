"""Voice gateway state machine — IDLE → LISTENING → PROCESSING → RESPONDING."""

from __future__ import annotations

import logging
import time
from enum import Enum, auto

logger = logging.getLogger(__name__)


class GatewayState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    RESPONDING = auto()


# Valid state transitions
_TRANSITIONS: dict[GatewayState, set[GatewayState]] = {
    GatewayState.IDLE: {GatewayState.LISTENING, GatewayState.PROCESSING},
    GatewayState.LISTENING: {GatewayState.IDLE, GatewayState.PROCESSING},
    GatewayState.PROCESSING: {GatewayState.IDLE, GatewayState.RESPONDING},
    GatewayState.RESPONDING: {GatewayState.IDLE},
}


class StateMachine:
    """Four-state FSM for voice gateway pipeline orchestration."""

    def __init__(self) -> None:
        self._state = GatewayState.IDLE
        self._state_entered_at = time.monotonic()
        self._transition_count = 0

    @property
    def state(self) -> GatewayState:
        return self._state

    def time_in_state(self) -> float:
        """Seconds since entering current state."""
        return time.monotonic() - self._state_entered_at

    def can_transition(self, target: GatewayState) -> bool:
        return target in _TRANSITIONS.get(self._state, set())

    def transition(self, target: GatewayState, reason: str = "") -> bool:
        """Attempt a state transition. Returns True on success."""
        if not self.can_transition(target):
            logger.warning(
                "invalid_transition: %s → %s (reason=%s)",
                self._state.name, target.name, reason,
            )
            return False

        prev = self._state
        self._state = target
        self._state_entered_at = time.monotonic()
        self._transition_count += 1
        logger.info(
            "state_changed: %s → %s (reason=%s)",
            prev.name, target.name, reason,
        )
        return True

    def reset(self) -> None:
        """Force reset to IDLE."""
        if self._state != GatewayState.IDLE:
            logger.info("state_reset: %s → IDLE", self._state.name)
        self._state = GatewayState.IDLE
        self._state_entered_at = time.monotonic()

    def status(self) -> dict:
        return {
            "state": self._state.name,
            "time_in_state_s": round(self.time_in_state(), 1),
            "transitions": self._transition_count,
        }
