"""Action Journal — append-only event log with state checkpoints.

Event sourcing primitives:
- Forward replay: State₁ + Action₁ = State₂
- Backward replay (undo): recompute from last checkpoint
- Diff: find actions between two points in time
- Crash recovery: checkpoint + replay = current state
"""

from __future__ import annotations

import time
from typing import Any

from src.shared.actions import Action, ReducerFn


class ActionJournal:
    """Append-only journal for event sourcing, crash recovery, and undo.

    Stores (action, timestamp) pairs with periodic state checkpoints to
    enable efficient replay without replaying from the beginning every time.

    Usage::

        j = ActionJournal(checkpoint_interval=100)
        state = reducer.initial_state
        for action in actions:
            state = reducer(state, action)
            j.append(action, state)

        # Replay to current
        current = j.replay(reducer)

        # Undo last 3 actions
        previous = j.undo(reducer, n=3)
    """

    def __init__(
        self,
        checkpoint_interval: int = 100,
        max_actions: int = 10000,
    ) -> None:
        # (action, timestamp) — immutable actions, monotonic timestamps
        self._actions: list[tuple[Action, float]] = []
        # (action_idx_after, state_snapshot, timestamp)
        # action_idx_after = len(_actions) at checkpoint time
        self._checkpoints: list[tuple[int, Any, float]] = []
        self._checkpoint_interval = checkpoint_interval
        self._max_actions = max_actions

    # ── Write ─────────────────────────────────────────────────────────────

    def append(self, action: Action, state: Any) -> None:
        """Record action + auto-checkpoint every N actions.

        The state snapshot is taken AFTER the action has been applied
        (post-reducer state), so checkpoints are self-consistent.
        """
        self._actions.append((action, time.monotonic()))

        # Auto-checkpoint every checkpoint_interval actions
        if len(self._actions) % self._checkpoint_interval == 0:
            self._checkpoints.append((len(self._actions), state, time.monotonic()))

        # Trim oldest if over max
        if len(self._actions) > self._max_actions:
            self._trim()

    # ── Read / Replay ─────────────────────────────────────────────────────

    def replay(self, reducer: ReducerFn, from_idx: int = 0) -> Any:
        """Forward replay actions and return resulting state.

        Args:
            reducer: Pure reducer function (must have .initial_state).
            from_idx: Number of actions to replay (0 = all actions).

        Returns:
            State after replaying the specified number of actions.
        """
        # from_idx=0 means "replay all", otherwise replay exactly from_idx actions
        end = len(self._actions) if from_idx == 0 else from_idx

        # Find nearest checkpoint with cp_idx <= end
        state: Any = reducer.initial_state
        start = 0
        for cp_idx, cp_state, _ in reversed(self._checkpoints):
            if cp_idx <= end:
                state = cp_state
                start = cp_idx
                break

        for action, _ in self._actions[start:end]:
            state = reducer(state, action)

        return state

    def undo(self, reducer: ReducerFn, n: int = 1) -> Any:
        """Undo last N actions by replaying all preceding actions.

        Args:
            reducer: Pure reducer function with .initial_state.
            n: Number of actions to undo.

        Returns:
            State as if the last n actions never happened.
        """
        target_idx = max(0, len(self._actions) - n)
        return self.replay(reducer, from_idx=target_idx)

    # ── Query ─────────────────────────────────────────────────────────────

    def get_actions_since(self, idx: int) -> list[Action]:
        """Get actions from idx (inclusive) to current end.

        Args:
            idx: 0-based start index into the action list.
        """
        return [a for a, _ in self._actions[idx:]]

    def get_actions_between(self, start_idx: int, end_idx: int) -> list[Action]:
        """Get actions between two indices (start inclusive, end exclusive).

        Args:
            start_idx: 0-based start index.
            end_idx: 0-based end index (exclusive).
        """
        return [a for a, _ in self._actions[start_idx:end_idx]]

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Number of recorded actions."""
        return len(self._actions)

    @property
    def checkpoint_count(self) -> int:
        """Number of stored checkpoints."""
        return len(self._checkpoints)

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize journal state for persistence.

        Returns a JSON-safe dict. States must be serializable by the caller.
        """
        return {
            "checkpoint_interval": self._checkpoint_interval,
            "max_actions": self._max_actions,
            "actions": [(a.type, a.payload, t) for a, t in self._actions],
            "checkpoints": [(idx, state, t) for idx, state, t in self._checkpoints],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        action_factory: Any = None,
    ) -> ActionJournal:
        """Restore journal from persisted state.

        Args:
            data: Dict produced by to_dict().
            action_factory: Optional callable(type, payload) → Action.
                            Defaults to Action(type=..., payload=...).
        """
        journal = cls(
            checkpoint_interval=data.get("checkpoint_interval", 100),
            max_actions=data.get("max_actions", 10000),
        )

        if action_factory is None:

            def action_factory(action_type: str, payload: Any) -> Action:
                return Action(type=action_type, payload=payload)

        journal._actions = [(action_factory(t, p), ts) for t, p, ts in data.get("actions", [])]
        journal._checkpoints = [(idx, state, ts) for idx, state, ts in data.get("checkpoints", [])]

        return journal

    # ── Internal ──────────────────────────────────────────────────────────

    def _trim(self) -> None:
        """Remove oldest actions beyond max_actions.

        Keeps actions from the most recent checkpoint onward to preserve
        replay correctness. Always retains at least one checkpoint.
        If no checkpoints exist, trims to the last max_actions entries.
        """
        if not self._checkpoints:
            # No checkpoints — simple tail truncation
            trim_count = len(self._actions) - self._max_actions
            self._actions = self._actions[trim_count:]
            return

        # Find the most recent checkpoint we can anchor to
        # Keep actions from that checkpoint onward
        last_cp_idx, last_cp_state, last_cp_ts = self._checkpoints[-1]

        # How many actions to drop (everything before last checkpoint)
        # last_cp_idx is the count of actions AT checkpoint time (1-based count)
        # so actions[0:last_cp_idx] were captured; we start from last_cp_idx
        trim_count = last_cp_idx

        if trim_count <= 0:
            return

        self._actions = self._actions[trim_count:]

        # Remove all checkpoints except the last (which is now at idx=0)
        # and shift its idx to 0 (the checkpoint state is the starting point)
        # The checkpoint at trim_count → now represents "start" (idx=0)
        self._checkpoints = [(0, last_cp_state, last_cp_ts)]

    def __repr__(self) -> str:
        return (
            f"ActionJournal(size={self.size}, "
            f"checkpoints={self.checkpoint_count}, "
            f"interval={self._checkpoint_interval})"
        )
