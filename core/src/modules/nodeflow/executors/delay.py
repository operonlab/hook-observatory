"""Delay executor — waits N seconds then passes through."""

import asyncio
from typing import Any

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult

MAX_DELAY = 300  # 5 minutes cap


class DelayExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Wait for a configured duration then pass data through.

        Config schema:
            {"seconds": 10}
        """
        seconds = min(config.get("seconds", 0), MAX_DELAY)
        if seconds > 0:
            await asyncio.sleep(seconds)
        return ExecutionResult(data=ctx.input_data)
