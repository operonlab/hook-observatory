"""FSM infrastructure — explicit state management for Workshop entities.

Integrates with BaseCRUDService hooks and EventBus for automatic
state transition validation, audit logging, and domain event emission.

Usage in a service:

    class UserService(StatefulCRUDService[User, UserCreate, UserUpdate, UserResponse]):
        model = User
        lifecycle_class = UserLifecycle
        status_field = "status"
"""

from __future__ import annotations

from typing import Any

from statemachine import StateMachine

from src.events.bus import Event, event_bus
from src.shared.errors import WorkshopError


class InvalidTransitionError(WorkshopError):
    """Raised when a state transition is not allowed by the FSM."""

    status_code = 409
    code = "system.invalid_transition"

    def __init__(self, entity_type: str, current: str, target: str):
        self.current_state = current
        self.target_state = target
        detail = f"{entity_type}: transition {current} -> {target} is not allowed"
        super().__init__(detail, code=f"{entity_type}.invalid_transition")


def get_valid_transitions(machine_cls: type[StateMachine]) -> dict[str, list[str]]:
    """Extract transition table from a StateMachine class.

    Returns: {source_state_id: [target_state_id, ...]}
    """
    table: dict[str, list[str]] = {}
    for state in machine_cls.states:
        table[state.id] = []
    for event in machine_cls.events:
        for transition in event._transitions:
            source_id = transition.source.id
            target_id = transition.target.id
            if target_id not in table[source_id]:
                table[source_id].append(target_id)
    return table


def validate_transition(
    machine_cls: type[StateMachine],
    current: str,
    target: str,
    entity_type: str = "",
) -> None:
    """Validate that a state transition is allowed.

    Raises InvalidTransitionError if the transition is not in the FSM.
    No-op if current == target (no actual transition).
    """
    if current == target:
        return

    table = get_valid_transitions(machine_cls)
    if current not in table:
        raise InvalidTransitionError(entity_type, current, target)
    if target not in table[current]:
        raise InvalidTransitionError(entity_type, current, target)


async def emit_state_changed(
    module: str,
    entity_type: str,
    entity_id: str,
    old_state: str,
    new_state: str,
    user_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Publish a state_changed domain event via EventBus."""
    event_type = f"{module}.{entity_type}.state_changed"
    data = {
        "entity_id": entity_id,
        "old_state": old_state,
        "new_state": new_state,
        **(extra or {}),
    }
    await event_bus.publish(
        Event(
            type=event_type,
            data=data,
            source=f"{module}.fsm",
            user_id=user_id,
        )
    )
