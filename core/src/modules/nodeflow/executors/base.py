"""Base executor — abstract interface for all node types."""

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
    """Interface that every node type executor must implement."""

    @abstractmethod
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Execute the node and return a result.

        Args:
            config: Node-specific JSONB config from the DB.
            ctx: Execution context with DB session, input data, etc.

        Returns:
            ExecutionResult with output data and the chosen output port.
        """
        ...
