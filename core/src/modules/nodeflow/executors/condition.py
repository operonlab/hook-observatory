"""Condition executor — evaluates if/else and routes to true/false port."""

import operator
from typing import Any

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult

_OPS: dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in a,
    "exists": lambda a, _: a is not None,
}


class ConditionExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Evaluate a condition and return via 'true' or 'false' port.

        Config schema:
            {
                "field": "amount",
                "operator": ">",
                "value": 1000
            }
        """
        field = config.get("field", "")
        op_name = config.get("operator", "==")
        expected = config.get("value")

        actual = ctx.input_data.get(field)

        # Coerce types for comparison
        if isinstance(expected, (int, float)) and isinstance(actual, str):
            try:
                actual = type(expected)(actual)
            except (ValueError, TypeError):
                pass

        op_fn = _OPS.get(op_name, operator.eq)
        try:
            result = op_fn(actual, expected)
        except (TypeError, ValueError):
            result = False

        port = "true" if result else "false"
        return ExecutionResult(
            data={**ctx.input_data, "_condition_result": result},
            output_port=port,
        )
