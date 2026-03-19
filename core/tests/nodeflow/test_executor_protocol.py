"""Tests: Nodeflow executors satisfy Operator Protocol (Reactive Phase 3)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.nodeflow.executors import EXECUTOR_MAP
from src.modules.nodeflow.executors.condition import ConditionExecutor
from src.modules.nodeflow.executors.delay import DelayExecutor
from src.modules.nodeflow.executors.transform import TransformExecutor
from src.modules.nodeflow.executors.trigger import TriggerExecutor
from src.shared.reactive import Operator


def _make_ctx(**overrides) -> dict:
    """Build a minimal Operator-mode ctx dict with mock db."""
    ctx = {
        "db": MagicMock(spec=AsyncSession),
        "space_id": "sp_test",
        "user_id": "u_test",
        "flow_run_id": "run_001",
        "input_data": {},
        "node_config": {},
    }
    ctx.update(overrides)
    return ctx


# ── TestProtocolCompliance ──────────────────────────────────────────────


class TestProtocolCompliance:
    def test_all_executors_are_operators(self):
        """Every executor in EXECUTOR_MAP satisfies Operator Protocol."""
        for key, cls in EXECUTOR_MAP.items():
            instance = cls()
            assert isinstance(instance, Operator), (
                f"{cls.__name__} (key={key}) does not satisfy Operator Protocol"
            )

    def test_name_matches_executor_map_key(self):
        """exec.name must equal its EXECUTOR_MAP key."""
        for key, cls in EXECUTOR_MAP.items():
            instance = cls()
            assert instance.name == key, (
                f"{cls.__name__}.name = '{instance.name}', expected '{key}'"
            )


# ── TestOperatorBridge ──────────────────────────────────────────────────


class TestOperatorBridge:
    @pytest.mark.asyncio
    async def test_trigger_call(self):
        """TriggerExecutor.__call__ passes input_data through as node_output."""
        ctx = _make_ctx(input_data={"event": "user.signup"})
        result = await TriggerExecutor()(ctx)
        assert result["node_output"] == {"event": "user.signup"}
        assert result["output_port"] == "output"

    @pytest.mark.asyncio
    async def test_transform_call(self):
        """TransformExecutor.__call__ applies mappings correctly."""
        ctx = _make_ctx(
            input_data={"amount": 100, "currency": "TWD"},
            node_config={
                "mappings": {
                    "total": "input.amount",
                    "unit": "input.currency",
                    "label": "literal:transformed",
                }
            },
        )
        result = await TransformExecutor()(ctx)
        assert result["node_output"] == {
            "total": 100,
            "unit": "TWD",
            "label": "transformed",
        }

    @pytest.mark.asyncio
    async def test_condition_call_true_port(self):
        """ConditionExecutor routes to 'true' port when condition met."""
        ctx = _make_ctx(
            input_data={"amount": 2000},
            node_config={"field": "amount", "operator": ">", "value": 1000},
        )
        result = await ConditionExecutor()(ctx)
        assert result["output_port"] == "true"

    @pytest.mark.asyncio
    async def test_condition_call_false_port(self):
        """ConditionExecutor routes to 'false' port when condition not met."""
        ctx = _make_ctx(
            input_data={"amount": 500},
            node_config={"field": "amount", "operator": ">", "value": 1000},
        )
        result = await ConditionExecutor()(ctx)
        assert result["output_port"] == "false"

    @pytest.mark.asyncio
    async def test_delay_call_zero_seconds(self):
        """DelayExecutor with seconds=0 passes through immediately."""
        ctx = _make_ctx(
            input_data={"msg": "hello"},
            node_config={"seconds": 0},
        )
        result = await DelayExecutor()(ctx)
        assert result["node_output"] == {"msg": "hello"}
        assert result["output_port"] == "output"


# ── TestOperatorMetadata ────────────────────────────────────────────────


class TestOperatorMetadata:
    def test_input_keys_default(self):
        assert TriggerExecutor().input_keys == ("input_data",)

    def test_output_keys_default(self):
        assert TriggerExecutor().output_keys == ("node_output", "output_port")
