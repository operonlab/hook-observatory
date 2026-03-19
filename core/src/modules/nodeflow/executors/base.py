"""Base executor — abstract interface for all node types.

Implements Operator Protocol (reactive.py) so executors can participate
in Pipeline.pipe() chains while keeping the existing engine.execute() path.
"""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class ExecutionContext:
    """Carries state through the DAG execution pipeline."""

    __slots__ = ("db", "flow_run_id", "input_data", "space_id", "user_id")

    def __init__(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None,
        flow_run_id: str,
        input_data: dict[str, Any],
    ):
        self.db = db
        self.space_id = space_id
        self.user_id = user_id
        self.flow_run_id = flow_run_id
        self.input_data = input_data


class ExecutionResult:
    """Result of executing a single node."""

    __slots__ = ("data", "output_port")

    def __init__(self, data: dict[str, Any], output_port: str = "output"):
        self.data = data
        self.output_port = output_port


class BaseNodeExecutor(ABC):
    """Interface that every node type executor must implement.

    Dual interface:
      - execute(config, ctx) — called by engine.py (DAG mode)
      - __call__(ctx)        — Operator Protocol (pipe chain mode)
    """

    @abstractmethod
    async def execute(self, config: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
        """Execute the node and return a result.

        Args:
            config: Node-specific JSONB config from the DB.
            ctx: Execution context with DB session, input data, etc.

        Returns:
            ExecutionResult with output data and the chosen output port.
        """
        ...

    # ── Operator Protocol — default implementation ──────────────────────

    @property
    def name(self) -> str:
        """TriggerExecutor → 'trigger', ConditionExecutor → 'condition'."""
        return type(self).__name__.replace("Executor", "").lower()

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("input_data",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("node_output", "output_port")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Operator Protocol bridge: flat ctx dict → execute() → updated ctx."""
        exec_ctx = ExecutionContext(
            db=ctx["db"],
            space_id=ctx["space_id"],
            user_id=ctx.get("user_id"),
            flow_run_id=ctx.get("flow_run_id", ""),
            input_data=ctx.get("input_data", {}),
        )
        result = await self.execute(ctx.get("node_config", {}), exec_ctx)
        ctx["node_output"] = result.data
        ctx["output_port"] = result.output_port
        return ctx
