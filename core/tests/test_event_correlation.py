"""Tests for correlation_id (trace_id) propagation through EventBus chains."""

import pytest
from src.events.backends.memory import InMemoryBackend
from src.events.bus import Event, EventBus, current_trace_id


@pytest.fixture
def bus() -> EventBus:
    return EventBus(backend=InMemoryBackend())


@pytest.mark.asyncio
async def test_follow_up_event_inherits_trace_id(bus: EventBus) -> None:
    """Event published inside a handler should inherit the parent's trace_id."""
    captured: list[str] = []

    async def handle_order_placed(event: Event) -> None:
        # Publish a follow-up event without explicitly passing trace_id
        follow_up = Event(type="invoice.created", data={"order_id": "123"})
        captured.append(follow_up.trace_id)
        await bus.publish(follow_up)

    bus.channel("order.placed").subscribe_handler(handle_order_placed)

    parent = Event(type="order.placed", data={})
    parent_trace = parent.trace_id
    await bus.publish(parent)

    assert len(captured) == 1, "Follow-up event was not created"
    assert captured[0] == parent_trace, (
        f"Follow-up trace_id {captured[0]!r} != parent trace_id {parent_trace!r}"
    )


@pytest.mark.asyncio
async def test_event_outside_handler_gets_own_trace_id(bus: EventBus) -> None:
    """Event published outside any handler should generate its own trace_id."""
    event_a = Event(type="standalone.a", data={})
    event_b = Event(type="standalone.b", data={})

    assert event_a.trace_id != event_b.trace_id, (
        "Two independent events should have distinct trace_ids"
    )
    # current_trace_id() should be None outside of handler context
    assert current_trace_id() is None


@pytest.mark.asyncio
async def test_explicit_trace_id_overrides_context(bus: EventBus) -> None:
    """Explicitly passed trace_id must win over the inherited context value."""
    captured: list[str] = []
    explicit_trace = "explicit-trace-0000"

    async def handle_task(event: Event) -> None:
        # Pass an explicit trace_id — should NOT inherit from context
        child = Event(type="task.step", data={}, trace_id=explicit_trace)
        captured.append(child.trace_id)

    bus.channel("task.started").subscribe_handler(handle_task)

    parent = Event(type="task.started", data={})
    parent_trace = parent.trace_id
    await bus.publish(parent)

    assert len(captured) == 1
    assert captured[0] == explicit_trace, (
        f"Expected explicit trace {explicit_trace!r}, got {captured[0]!r}"
    )
    assert captured[0] != parent_trace, (
        "Explicit trace_id should override inherited context"
    )


@pytest.mark.asyncio
async def test_context_reset_after_handler(bus: EventBus) -> None:
    """ContextVar must be reset to None after handler finishes."""

    async def handle_reset(event: Event) -> None:
        pass  # Just consume the event

    bus.channel("reset.test").subscribe_handler(handle_reset)

    await bus.publish(Event(type="reset.test", data={}))
    # After dispatch, context should be back to None
    assert current_trace_id() is None


@pytest.mark.asyncio
async def test_deep_chain_preserves_trace_id(bus: EventBus) -> None:
    """Three-level chain: A -> B -> C all share the root trace_id."""
    root_trace: list[str] = []
    chain_traces: list[str] = []

    async def handle_a(event: Event) -> None:
        root_trace.append(event.trace_id)
        await bus.publish(Event(type="chain.b", data={}))

    async def handle_b(event: Event) -> None:
        chain_traces.append(event.trace_id)
        await bus.publish(Event(type="chain.c", data={}))

    async def handle_c(event: Event) -> None:
        chain_traces.append(event.trace_id)

    bus.channel("chain.a").subscribe_handler(handle_a)
    bus.channel("chain.b").subscribe_handler(handle_b)
    bus.channel("chain.c").subscribe_handler(handle_c)

    root = Event(type="chain.a", data={})
    await bus.publish(root)

    assert len(root_trace) == 1
    assert len(chain_traces) == 2
    assert chain_traces[0] == root.trace_id, "chain.b should share root trace_id"
    assert chain_traces[1] == root.trace_id, "chain.c should share root trace_id"
