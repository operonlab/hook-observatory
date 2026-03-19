"""Tests for EventChannel — Reactive-Native EventBus API."""

import pytest
from src.events.backends.memory import InMemoryBackend
from src.events.bus import Event, EventBus
from src.events.channel import _PipedChannel
from src.modules.memvault.reactive_adapters import (
    EmbeddingScheduler,
    NoiseGateOp,
    TagCooccurrenceOp,
)
from src.shared.reactive import (
    FunctionObserver,
    Observable,
    Observer,
    Operator,
    Scheduler,
    Subject,
    Subscription,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_bus() -> EventBus:
    """Fresh in-memory EventBus for test isolation."""
    return EventBus(backend=InMemoryBackend())


# ═══════════════════════════════════════════════════════════════════════════
# Protocol Compliance — isinstance checks
# ═══════════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    def test_event_channel_subject_protocol(self):
        bus = _make_bus()
        ch = bus.channel("test.event")
        assert isinstance(ch, Subject)

    def test_event_channel_observable_protocol(self):
        bus = _make_bus()
        ch = bus.channel("test.event")
        assert isinstance(ch, Observable)

    def test_function_observer_protocol(self):
        obs = FunctionObserver(lambda v: None)
        assert isinstance(obs, Observer)

    def test_scheduler_protocol(self):
        scheduler = EmbeddingScheduler(3)
        assert isinstance(scheduler, Scheduler)

    def test_noise_gate_operator_protocol(self):
        assert isinstance(NoiseGateOp(), Operator)

    def test_tag_cooccurrence_operator_protocol(self):
        assert isinstance(TagCooccurrenceOp(), Operator)


# ═══════════════════════════════════════════════════════════════════════════
# EventChannel subscribe / unsubscribe lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestEventChannel:
    @pytest.mark.asyncio
    async def test_subscribe_handler_receives_event(self):
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event)

        bus.channel("test.event").subscribe_handler(handler)
        await bus.publish(Event(type="test.event", data={"key": "value"}, source="test"))

        assert len(received) == 1
        assert received[0].data["key"] == "value"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event)

        sub = bus.channel("test.event").subscribe_handler(handler)
        await bus.publish(Event(type="test.event", data={"n": 1}, source="test"))
        assert len(received) == 1

        sub.unsubscribe()
        await bus.publish(Event(type="test.event", data={"n": 2}, source="test"))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = _make_bus()
        a_received, b_received = [], []

        async def handler_a(event):
            a_received.append(event)

        async def handler_b(event):
            b_received.append(event)

        bus.channel("test.event").subscribe_handler(handler_a)
        bus.channel("test.event").subscribe_handler(handler_b)

        await bus.publish(Event(type="test.event", data={"msg": "hello"}, source="test"))

        assert len(a_received) == 1
        assert len(b_received) == 1

    @pytest.mark.asyncio
    async def test_subscription_is_subscription_type(self):
        bus = _make_bus()

        async def noop(event):
            pass

        sub = bus.channel("test.event").subscribe_handler(noop)
        assert isinstance(sub, Subscription)
        sub.unsubscribe()
        assert sub.closed

    @pytest.mark.asyncio
    async def test_channel_cached(self):
        bus = _make_bus()
        ch1 = bus.channel("test.event")
        ch2 = bus.channel("test.event")
        assert ch1 is ch2


# ═══════════════════════════════════════════════════════════════════════════
# pipe + operators
# ═══════════════════════════════════════════════════════════════════════════


class TestPipeOperators:
    @pytest.mark.asyncio
    async def test_pipe_chains_operators(self):
        bus = _make_bus()
        received = []

        async def handler(ctx):
            received.append(ctx)

        piped = bus.channel("test.event").pipe(NoiseGateOp(), TagCooccurrenceOp())
        piped.subscribe(FunctionObserver(handler))

        await bus.publish(
            Event(
                type="test.event",
                data={
                    "content": "Learning about reactive programming patterns in Python",
                    "tags": ["reactive", "python", "patterns"],
                },
                source="test",
            )
        )

        assert len(received) == 1
        ctx = received[0]
        assert ctx["is_noise"] is False
        assert len(ctx["triple_dicts"]) == 3

    @pytest.mark.asyncio
    async def test_pipe_returns_piped_channel(self):
        bus = _make_bus()
        piped = bus.channel("test.event").pipe(NoiseGateOp())
        assert isinstance(piped, _PipedChannel)

    @pytest.mark.asyncio
    async def test_double_pipe(self):
        bus = _make_bus()
        piped = bus.channel("test.event").pipe(NoiseGateOp()).pipe(TagCooccurrenceOp())
        received = []

        async def handler(ctx):
            received.append(ctx)

        piped.subscribe(FunctionObserver(handler))

        await bus.publish(
            Event(
                type="test.event",
                data={"content": "meaningful content", "tags": ["a", "b"]},
                source="test",
            )
        )

        assert len(received) == 1
        assert "is_noise" in received[0]
        assert "triple_dicts" in received[0]


# ═══════════════════════════════════════════════════════════════════════════
# FunctionObserver sync/async
# ═══════════════════════════════════════════════════════════════════════════


class TestFunctionObserver:
    @pytest.mark.asyncio
    async def test_async_handler(self):
        received = []

        async def handler(v):
            received.append(v)

        obs = FunctionObserver(handler)
        await obs.on_next({"data": 42})
        assert received == [{"data": 42}]

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        received = []
        obs = FunctionObserver(lambda v: received.append(v))
        await obs.on_next({"data": 99})
        assert received == [{"data": 99}]

    @pytest.mark.asyncio
    async def test_on_error_does_not_raise(self):
        obs = FunctionObserver(lambda v: None)
        await obs.on_error(ValueError("test"))

    @pytest.mark.asyncio
    async def test_on_complete_does_not_raise(self):
        obs = FunctionObserver(lambda v: None)
        await obs.on_complete()


# ═══════════════════════════════════════════════════════════════════════════
# EventBus.stop() auto-cleanup
# ═══════════════════════════════════════════════════════════════════════════


class TestBusStopCleanup:
    @pytest.mark.asyncio
    async def test_stop_unsubscribes_all(self):
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event)

        bus.channel("test.event").subscribe_handler(handler)
        await bus.publish(Event(type="test.event", data={}, source="test"))
        assert len(received) == 1

        await bus.stop()
        # After stop, all subscriptions cleaned — handler registry empty
        assert len(bus._backend.handlers.get("test.event", [])) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Wildcard channel "*"
# ═══════════════════════════════════════════════════════════════════════════


class TestWildcardChannel:
    @pytest.mark.asyncio
    async def test_wildcard_receives_all_events(self):
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event.type)

        bus.channel("*").subscribe_handler(handler)
        await bus.publish(Event(type="foo.bar", data={}, source="test"))
        await bus.publish(Event(type="baz.qux", data={}, source="test"))

        assert received == ["foo.bar", "baz.qux"]
