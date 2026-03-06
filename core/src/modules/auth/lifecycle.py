"""Auth FSM — User lifecycle state machine.

States:
    pending   (initial) — Email registration, awaiting admin approval
    active              — Fully operational user
    suspended           — Temporarily disabled
    banned    (final)   — Permanently blocked, no recovery

Note: OAuth users are created directly as ``active`` by the service layer;
this does not require an FSM transition from ``pending``.
"""

from statemachine import State, StateMachine


class UserLifecycle(StateMachine):
    """Declarative user status transitions."""

    # States
    pending = State(initial=True)
    active = State()
    suspended = State()
    banned = State(final=True)

    # Transitions
    approve = pending.to(active)
    reject = pending.to(banned)
    suspend = active.to(suspended)
    ban = active.to(banned) | suspended.to(banned)
    reactivate = suspended.to(active)
