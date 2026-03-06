"""Finance FSM lifecycles — state machines for Transaction, Subscription, InstallmentPlan.

Each lifecycle defines valid states and transitions.  Used by services to
validate status changes before persisting them via ``validate_transition()``.

    from src.shared.fsm import validate_transition
    from src.modules.finance.lifecycle import TransactionLifecycle

    validate_transition(TransactionLifecycle, old_status, new_status, "transaction")
"""

from statemachine import State, StateMachine

# ======================== Transaction ========================


class TransactionLifecycle(StateMachine):
    """Transaction status: pending | scheduled | completed | cancelled.

    Transitions::

        pending   --complete--> completed
        pending   --cancel----> cancelled
        scheduled --activate--> pending
        scheduled --cancel----> cancelled
    """

    # States
    pending = State("Pending", initial=True)
    scheduled = State("Scheduled")
    completed = State("Completed", final=True)
    cancelled = State("Cancelled", final=True)

    # Transitions
    complete = pending.to(completed)
    cancel = pending.to(cancelled) | scheduled.to(cancelled)
    schedule = pending.to(scheduled)
    activate = scheduled.to(pending)


# ======================== Subscription ========================


class SubscriptionLifecycle(StateMachine):
    """Subscription status: active | paused | cancelled.

    Transitions::

        active --pause---> paused
        paused --resume--> active
        active --cancel--> cancelled
        paused --cancel--> cancelled
    """

    # States
    active = State("Active", initial=True)
    paused = State("Paused")
    cancelled = State("Cancelled", final=True)

    # Transitions
    pause = active.to(paused)
    resume = paused.to(active)
    cancel = active.to(cancelled) | paused.to(cancelled)


# ======================== Installment Plan ========================


class InstallmentLifecycle(StateMachine):
    """Installment plan status: active | completed | cancelled.

    Transitions::

        active --complete--> completed
        active --cancel----> cancelled
    """

    # States
    active = State("Active", initial=True)
    completed = State("Completed", final=True)
    cancelled = State("Cancelled", final=True)

    # Transitions
    complete = active.to(completed)
    cancel = active.to(cancelled)
