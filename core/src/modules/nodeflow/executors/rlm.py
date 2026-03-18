"""RLM executor — runs Recursive Language Model inference as a DAG node."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.shared.rlm_engine import RLMConfig, RLMEngine

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult

logger = structlog.get_logger()


class RLMExecutor(BaseNodeExecutor):
    async def execute(self, config: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
        """Run RLM inference and return the response.

        Config schema:
            {
                "prompt": "Analyze this data and find patterns.",
                "context_source": "input",   # "input" | "variable" | "literal"
                "context_value": "...",       # template key or literal text
                "model": "grok-4-fast",
                "max_iterations": 10
            }

        context_source:
            - "input": use ctx.input_data as context (JSON-serialized)
            - "variable": resolve {{variable_name}} from ctx.input_data
            - "literal": use context_value as-is
        """
        prompt = config.get("prompt", "")
        if not prompt:
            raise ValueError("RLM node requires a 'prompt' in config")

        context = _resolve_context(config, ctx)

        rlm_config = RLMConfig(
            model=config.get("model", "grok-4-fast"),
            max_iterations=config.get("max_iterations", 10),
            api_base=config.get("api_base", "http://localhost:4000/v1"),
            api_key=config.get("api_key", "sk-litellm-local-dev"),
        )
        engine = RLMEngine(rlm_config)

        # RLMEngine.completion() is synchronous — run in thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: engine.completion(prompt=prompt, context=context)
        )

        logger.info(
            "rlm_executor.done",
            flow_run_id=ctx.flow_run_id,
            status=result.status,
            iterations=result.iterations,
            time_secs=round(result.execution_time_secs, 2),
        )

        return ExecutionResult(
            data={
                "response": result.response,
                "status": result.status,
                "iterations": result.iterations,
                "execution_time_secs": round(result.execution_time_secs, 2),
                "total_llm_calls": result.usage.total_calls,
            }
        )


def _resolve_context(config: dict[str, Any], ctx: ExecutionContext) -> str | None:
    """Resolve context from node config + execution context."""
    source = config.get("context_source", "input")
    value = config.get("context_value", "")

    if source == "input":
        if not ctx.input_data:
            return None
        # Serialize input data as readable text for RLM
        import json

        return json.dumps(ctx.input_data, ensure_ascii=False, indent=2, default=str)

    if source == "variable":
        # Resolve template variable from input data: {{key}}
        key = value.strip().strip("{}")
        resolved = ctx.input_data.get(key)
        return str(resolved) if resolved is not None else None

    if source == "literal":
        return value or None

    raise ValueError(f"Unknown context_source: {source!r}")
