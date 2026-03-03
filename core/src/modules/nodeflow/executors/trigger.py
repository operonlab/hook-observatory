"""Trigger executor — passes through the triggering event data."""

from typing import Any

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult


class TriggerExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        return ExecutionResult(data=ctx.input_data)
