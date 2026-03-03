"""Action executor — invokes a registered module service method."""

from typing import Any

import structlog

from ..registry import get_action
from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult

logger = structlog.get_logger()


class ActionExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Call module.action with resolved params.

        Config schema:
            {
                "module": "finance",
                "action": "create_transaction",
                "params": {"amount": "{{input.amount}}", "category_id": "..."}
            }
        """
        module = config.get("module", "")
        action_name = config.get("action", "")
        params = config.get("params", {})

        handler = get_action(module, action_name)
        if not handler:
            raise ValueError(f"Unknown action: {module}.{action_name}")

        # Resolve template variables from input data
        resolved = _resolve_params(params, ctx.input_data)

        # Call the service method with standard args
        result = await handler(
            ctx.db,
            ctx.space_id,
            **resolved,
        )

        # Normalize result to dict
        if hasattr(result, "model_dump"):
            output = result.model_dump(mode="json")
        elif isinstance(result, dict):
            output = result
        else:
            output = {"result": str(result)}

        return ExecutionResult(data=output)


def _resolve_params(params: dict, input_data: dict) -> dict:
    """Simple template resolution: {{input.key}} → input_data[key]."""
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
            path = v[2:-2].strip()
            if path.startswith("input."):
                key = path[6:]
                resolved[k] = input_data.get(key, v)
            else:
                resolved[k] = v
        else:
            resolved[k] = v
    return resolved
