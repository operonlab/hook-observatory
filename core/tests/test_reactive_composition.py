"""Tests for reactive composition tools."""

import pytest
from src.shared.reactive import (
    ConditionalOp,
    Operator,
    ParallelOp,
    Pipeline,
    ScheduledOp,
)

# ═══════════════════════════════════════════════════════════════════════════
# Test Helpers — simple Operators for composition testing
# ═══════════════════════════════════════════════════════════════════════════


class AddOp:
    """Adds `amount` to ctx["value"]."""

    def __init__(self, amount: int = 1) -> None:
        self._amount = amount

    name = "add"
    input_keys = ("value",)
    output_keys = ("value",)

    async def __call__(self, ctx):
        ctx["value"] = ctx.get("value", 0) + self._amount
        return ctx


class DoubleOp:
    """Doubles ctx["value"]."""

    name = "double"
    input_keys = ("value",)
    output_keys = ("value",)

    async def __call__(self, ctx):
        ctx["value"] = ctx.get("value", 0) * 2
        return ctx


class NeedOp:
    """Reads `source`, writes `result`."""

    name = "need"
    input_keys = ("source",)
    output_keys = ("result",)

    async def __call__(self, ctx):
        ctx["result"] = f"processed:{ctx.get('source', '')}"
        return ctx


class ProduceOp:
    """Produces `source` from nothing (for chain deduction tests)."""

    name = "produce"
    input_keys = ()
    output_keys = ("source",)

    async def __call__(self, ctx):
        ctx["source"] = "generated"
        return ctx


class FailOp:
    """Always raises."""

    name = "fail"
    input_keys = ()
    output_keys = ()

    async def __call__(self, ctx):
        raise RuntimeError("intentional failure")


# ═══════════════════════════════════════════════════════════════════════════
# TestConditionalOp
# ═══════════════════════════════════════════════════════════════════════════


class TestConditionalOp:
    @pytest.mark.asyncio
    async def test_true_path(self):
        op = ConditionalOp(predicate=lambda ctx: True, then_op=AddOp(10))
        result = await op({"value": 5})
        assert result["value"] == 15

    @pytest.mark.asyncio
    async def test_false_with_else_op(self):
        op = ConditionalOp(
            predicate=lambda ctx: False,
            then_op=AddOp(10),
            else_op=DoubleOp(),
        )
        result = await op({"value": 5})
        assert result["value"] == 10

    @pytest.mark.asyncio
    async def test_false_passthrough(self):
        op = ConditionalOp(predicate=lambda ctx: False, then_op=AddOp(10))
        result = await op({"value": 5})
        assert result["value"] == 5  # unchanged

    @pytest.mark.asyncio
    async def test_then_op_is_pipeline(self):
        pipe = Pipeline(name="add_then_double").pipe(AddOp(3), DoubleOp())
        op = ConditionalOp(predicate=lambda ctx: True, then_op=pipe)
        result = await op({"value": 4})
        # (4 + 3) * 2 = 14
        assert result["value"] == 14

    def test_input_keys_union(self):
        op = ConditionalOp(
            predicate=lambda ctx: True,
            then_op=AddOp(),
            else_op=NeedOp(),
            predicate_keys=("flag",),
        )
        keys = set(op.input_keys)
        assert "flag" in keys
        assert "value" in keys
        assert "source" in keys

    def test_output_keys_union(self):
        op = ConditionalOp(
            predicate=lambda ctx: True,
            then_op=AddOp(),
            else_op=NeedOp(),
        )
        keys = set(op.output_keys)
        assert "value" in keys
        assert "result" in keys


# ═══════════════════════════════════════════════════════════════════════════
# TestParallelOp
# ═══════════════════════════════════════════════════════════════════════════


class TestParallelOp:
    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        # NeedOp first (writes "result"), AddOp second (writes "value")
        # Later ops' full ctx wins on shared keys, so AddOp must be last
        op = ParallelOp(NeedOp(), AddOp(10), name="test_parallel")
        result = await op({"value": 1, "source": "hello"})
        assert result["value"] == 11
        assert result["result"] == "processed:hello"

    @pytest.mark.asyncio
    async def test_deepcopy_isolation(self):
        """Modifying one op's copy must not affect another's."""

        class TrackOp:
            name = "track"
            input_keys = ("items",)
            output_keys = ("tracked",)

            async def __call__(self, ctx):
                ctx["items"].append("mutated")
                ctx["tracked"] = len(ctx["items"])
                return ctx

        class ReadOp:
            name = "read"
            input_keys = ("items",)
            output_keys = ("count",)

            async def __call__(self, ctx):
                ctx["count"] = len(ctx["items"])
                return ctx

        op = ParallelOp(TrackOp(), ReadOp())
        result = await op({"items": ["a", "b"]})
        # ReadOp should see original list (2 items), not mutated (3)
        assert result["count"] == 2
        # TrackOp sees 3 (original 2 + "mutated")
        assert result["tracked"] == 3

    @pytest.mark.asyncio
    async def test_later_ops_overwrite(self):
        """When ops produce same key, later op result wins."""
        op = ParallelOp(AddOp(1), AddOp(100))
        result = await op({"value": 0})
        # Both write "value"; gather preserves order, last wins in merge
        assert result["value"] == 100

    @pytest.mark.asyncio
    async def test_one_op_exception(self):
        op = ParallelOp(AddOp(1), FailOp())
        with pytest.raises(RuntimeError, match="intentional failure"):
            await op({"value": 0})


# ═══════════════════════════════════════════════════════════════════════════
# TestScheduledOp
# ═══════════════════════════════════════════════════════════════════════════


class _MockScheduler:
    """Minimal Scheduler that records calls."""

    def __init__(self):
        self.calls = []

    async def schedule(self, work, *args, **kwargs):
        self.calls.append(work)
        return await work(*args, **kwargs)

    async def schedule_batch(self, items, processor):
        return [await processor(item) for item in items]


class TestScheduledOp:
    @pytest.mark.asyncio
    async def test_delegates_to_scheduler(self):
        scheduler = _MockScheduler()
        inner = AddOp(7)
        op = ScheduledOp(inner, scheduler)
        result = await op({"value": 3})
        assert result["value"] == 10
        assert len(scheduler.calls) == 1

    def test_preserves_operator_keys(self):
        scheduler = _MockScheduler()
        inner = NeedOp()
        op = ScheduledOp(inner, scheduler)
        assert op.input_keys == ("source",)
        assert op.output_keys == ("result",)
        assert "scheduled" in op.name


# ═══════════════════════════════════════════════════════════════════════════
# TestPipelineAsOperator
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineAsOperator:
    def test_pipeline_is_operator(self):
        pipe = Pipeline().pipe(AddOp())
        assert isinstance(pipe, Operator)

    def test_pipeline_name(self):
        pipe = Pipeline(name="my_pipe").pipe(AddOp())
        assert pipe.name == "my_pipe"

        pipe2 = Pipeline().pipe(AddOp(), DoubleOp())
        assert pipe2.name == "add → double"

    def test_input_keys_chain_deduction(self):
        """ProduceOp outputs 'source', NeedOp needs it -> not in input_keys."""
        pipe = Pipeline().pipe(ProduceOp(), NeedOp())
        assert "source" not in pipe.input_keys
        assert "result" in pipe.output_keys

    def test_output_keys_union(self):
        pipe = Pipeline().pipe(AddOp(), NeedOp())
        keys = set(pipe.output_keys)
        assert "value" in keys
        assert "result" in keys

    def test_empty_pipeline(self):
        pipe = Pipeline()
        assert pipe.name == "empty_pipeline"
        assert pipe.input_keys == ()
        assert pipe.output_keys == ()

    @pytest.mark.asyncio
    async def test_empty_pipeline_call(self):
        pipe = Pipeline()
        result = await pipe({"x": 1})
        assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_call_equals_execute(self):
        pipe = Pipeline().pipe(AddOp(5))
        ctx1 = await pipe({"value": 10})
        ctx2 = await pipe.execute({"value": 10})
        assert ctx1["value"] == ctx2["value"] == 15

    def test_compile_detects_missing(self):
        pipe = Pipeline().pipe(NeedOp())
        missing = pipe.compile(initial_keys=set())
        assert any("source" in m for m in missing)

    def test_compile_passes(self):
        pipe = Pipeline().pipe(ProduceOp(), NeedOp())
        missing = pipe.compile(initial_keys=set())
        assert missing == []

    def test_input_keys_matches_compile(self):
        """Pipeline.input_keys should report same missing keys as compile(set())."""
        pipe = Pipeline().pipe(AddOp(), NeedOp())
        compile_missing_keys = set()
        for msg in pipe.compile(initial_keys=set()):
            # Extract key name from "op_name: requires 'key'"
            key = msg.split("'")[1]
            compile_missing_keys.add(key)
        assert set(pipe.input_keys) == compile_missing_keys
