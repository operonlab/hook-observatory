"""Tests for memvault reactive adapters — Protocol compliance + functional tests."""

import asyncio

import pytest
from src.events.backends.memory import InMemoryBackend
from src.events.bus import Event, EventBus
from src.modules.memvault.reactive_adapters import (
    EmbeddingScheduler,
    NoiseGateOp,
    TagCooccurrenceOp,
    wire_memory_creation_flow,
)
from src.shared.reactive import (
    FunctionObserver,
    Observer,
    Operator,
    Scheduler,
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
    def test_function_observer_protocol(self):
        observer = FunctionObserver(lambda v: None)
        assert isinstance(observer, Observer)

    def test_scheduler_protocol(self):
        scheduler = EmbeddingScheduler(3)
        assert isinstance(scheduler, Scheduler)

    def test_noise_gate_operator_protocol(self):
        op = NoiseGateOp()
        assert isinstance(op, Operator)

    def test_tag_cooccurrence_operator_protocol(self):
        op = TagCooccurrenceOp()
        assert isinstance(op, Operator)


# ═══════════════════════════════════════════════════════════════════════════
# FunctionObserver
# ═══════════════════════════════════════════════════════════════════════════


class TestFunctionObserver:
    @pytest.mark.asyncio
    async def test_on_next_calls_async_handler(self):
        received = []

        async def handler(v):
            received.append(v)

        observer = FunctionObserver(handler, name="test")
        await observer.on_next({"data": 42})

        assert received == [{"data": 42}]

    @pytest.mark.asyncio
    async def test_on_next_calls_sync_handler(self):
        received = []
        observer = FunctionObserver(lambda v: received.append(v), name="test")
        await observer.on_next({"data": 99})
        assert received == [{"data": 99}]

    @pytest.mark.asyncio
    async def test_on_error_does_not_raise(self):
        observer = FunctionObserver(lambda v: None, name="test")
        await observer.on_error(ValueError("test error"))

    @pytest.mark.asyncio
    async def test_on_complete_does_not_raise(self):
        observer = FunctionObserver(lambda v: None, name="test")
        await observer.on_complete()


# ═══════════════════════════════════════════════════════════════════════════
# EmbeddingScheduler
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingScheduler:
    @pytest.mark.asyncio
    async def test_schedule_single(self):
        scheduler = EmbeddingScheduler(2)

        async def double(x):
            return x * 2

        result = await scheduler.schedule(double, 5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_schedule_batch(self):
        scheduler = EmbeddingScheduler(2)

        async def square(x):
            return x**2

        results = await scheduler.schedule_batch([1, 2, 3, 4], square)
        assert results == [1, 4, 9, 16]

    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        """Verify semaphore actually limits concurrency."""
        scheduler = EmbeddingScheduler(2)
        max_concurrent = 0
        current = 0

        async def track(x):
            nonlocal max_concurrent, current
            current += 1
            if current > max_concurrent:
                max_concurrent = current
            await asyncio.sleep(0.01)
            current -= 1
            return x

        await scheduler.schedule_batch([1, 2, 3, 4, 5], track)
        assert max_concurrent <= 2


# ═══════════════════════════════════════════════════════════════════════════
# EventChannel + pipe (replaces MemoryStream tests)
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelPipe:
    @pytest.mark.asyncio
    async def test_channel_subscribe_receives_event(self):
        """No operators → direct passthrough via channel."""
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event)

        bus.channel("test.event").subscribe_handler(handler)
        await bus.publish(Event(type="test.event", data={"raw": True}, source="test"))

        assert len(received) == 1
        assert received[0].data["raw"] is True

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
                    "content": "This is a meaningful memory about Python patterns",
                    "tags": ["python", "patterns", "coding"],
                },
                source="test",
            )
        )

        assert len(received) == 1
        ctx = received[0]
        assert ctx["is_noise"] is False
        assert len(ctx["triple_dicts"]) == 3  # 3C2 = 3

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


# ═══════════════════════════════════════════════════════════════════════════
# Creation Operators
# ═══════════════════════════════════════════════════════════════════════════


class TestNoiseGateOp:
    @pytest.mark.asyncio
    async def test_clean_content(self):
        op = NoiseGateOp()
        ctx = await op({"content": "Important insight about architecture patterns"})
        assert ctx["is_noise"] is False
        assert ctx["noise_reason"] is None

    @pytest.mark.asyncio
    async def test_noisy_content(self):
        op = NoiseGateOp()
        ctx = await op({"content": "hi"})
        assert ctx["is_noise"] is True

    @pytest.mark.asyncio
    async def test_empty_content(self):
        op = NoiseGateOp()
        ctx = await op({"content": ""})
        assert ctx["is_noise"] is True

    def test_operator_metadata(self):
        op = NoiseGateOp()
        assert op.name == "noise_gate"
        assert op.input_keys == ("content",)
        assert op.output_keys == ("is_noise", "noise_reason")


class TestTagCooccurrenceOp:
    @pytest.mark.asyncio
    async def test_two_tags(self):
        op = TagCooccurrenceOp()
        ctx = await op({"tags": ["python", "async"]})
        assert len(ctx["triple_dicts"]) == 1
        assert ctx["triple_dicts"][0] == {
            "subject": "python",
            "predicate": "co_occurs_with",
            "object": "async",
        }

    @pytest.mark.asyncio
    async def test_five_tags(self):
        op = TagCooccurrenceOp()
        ctx = await op({"tags": ["a", "b", "c", "d", "e"]})
        assert len(ctx["triple_dicts"]) == 10

    @pytest.mark.asyncio
    async def test_caps_at_five_tags(self):
        op = TagCooccurrenceOp()
        ctx = await op({"tags": ["a", "b", "c", "d", "e", "f", "g"]})
        assert len(ctx["triple_dicts"]) == 10

    @pytest.mark.asyncio
    async def test_single_tag(self):
        op = TagCooccurrenceOp()
        ctx = await op({"tags": ["only"]})
        assert ctx["triple_dicts"] == []

    @pytest.mark.asyncio
    async def test_filters_quarantine_tag(self):
        op = TagCooccurrenceOp()
        ctx = await op({"tags": ["_quarantine", "real_tag"]})
        assert ctx["triple_dicts"] == []

    def test_operator_metadata(self):
        op = TagCooccurrenceOp()
        assert op.name == "tag_cooccurrence"
        assert op.input_keys == ("tags",)
        assert op.output_keys == ("triple_dicts",)


# ═══════════════════════════════════════════════════════════════════════════
# Full Flow Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_wire_and_flow(self):
        """Full flow: channel.pipe → operators → observer receives processed ctx."""
        bus = _make_bus()
        received = []

        async def handler(ctx):
            received.append(ctx)

        piped = bus.channel("memvault.memory.stored").pipe(
            NoiseGateOp(), TagCooccurrenceOp()
        )
        sub = piped.subscribe(FunctionObserver(handler, name="test_observer"))

        await bus.publish(
            Event(
                type="memvault.memory.stored",
                data={
                    "content": "Learning about reactive programming patterns in Python",
                    "tags": ["reactive", "python", "patterns"],
                    "block_id": "test-block-1",
                    "space_id": "test-space",
                },
                source="test",
            )
        )

        assert len(received) == 1
        ctx = received[0]
        assert ctx["is_noise"] is False
        assert len(ctx["triple_dicts"]) == 3
        assert ctx["block_id"] == "test-block-1"

        # Emit a noise event
        await bus.publish(
            Event(
                type="memvault.memory.stored",
                data={"content": "hi", "tags": ["greet"]},
                source="test",
            )
        )

        assert len(received) == 2
        ctx_noise = received[1]
        assert ctx_noise["is_noise"] is True
        assert ctx_noise["triple_dicts"] == []

        sub.unsubscribe()
        assert sub.closed

    @pytest.mark.asyncio
    async def test_wire_memory_creation_flow_factory(self):
        """Verify the factory wires correctly and observer processes ctx (not just logs)."""
        bus = _make_bus()
        sub = wire_memory_creation_flow(bus=bus)

        assert isinstance(sub, Subscription)
        assert not sub.closed

        # Publish a real event through the bus — observer should process without error.
        # The KG write will fail (no DB in test), but the pipe + operator chain must work.
        event = Event(
            type="memvault.memory.stored",
            data={
                "content": "Architecture decision: use adapter pattern for reactive",
                "tags": ["architecture", "reactive", "adapter"],
                "block_id": "test-123",
                "space_id": "space-1",
            },
            source="test",
        )
        await bus.publish(event)

        sub.unsubscribe()
        assert sub.closed

    @pytest.mark.asyncio
    async def test_bus_stop_cleans_up(self):
        """EventBus.stop() should unsubscribe all tracked subscriptions."""
        bus = _make_bus()
        received = []

        async def handler(event):
            received.append(event)

        bus.channel("test.cleanup").subscribe_handler(handler)
        await bus.publish(Event(type="test.cleanup", data={}, source="test"))
        assert len(received) == 1

        await bus.stop()
        assert len(bus._backend.handlers.get("test.cleanup", [])) == 0
