"""Transform executor — data mapping and reshaping."""

from typing import Any

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult


class TransformExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Map input fields to output fields.

        Config schema:
            {
                "mappings": {
                    "output_key": "input.source_key",
                    "static_key": "literal:some_value"
                }
            }
        """
        mappings: dict[str, str] = config.get("mappings", {})
        output: dict[str, Any] = {}

        for out_key, source in mappings.items():
            if source.startswith("input."):
                input_key = source[6:]
                output[out_key] = ctx.input_data.get(input_key)
            elif source.startswith("literal:"):
                output[out_key] = source[8:]
            else:
                output[out_key] = ctx.input_data.get(source)

        return ExecutionResult(data=output)
