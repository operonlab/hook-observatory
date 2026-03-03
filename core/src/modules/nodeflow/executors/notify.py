"""Notify executor — publishes a notification event."""

from typing import Any

from src.events.bus import Event, event_bus

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult


class NotifyExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Publish a notification via EventBus.

        Config schema:
            {
                "title": "Stock dividend received",
                "message": "{{input.symbol}} paid {{input.amount}}",
                "level": "info"
            }
        """
        title = _resolve(config.get("title", "Notification"), ctx.input_data)
        message = _resolve(config.get("message", ""), ctx.input_data)
        level = config.get("level", "info")

        await event_bus.publish(Event(
            type="system.notification.created",
            data={
                "title": title,
                "message": message,
                "level": level,
                "source": "nodeflow",
                "flow_run_id": ctx.flow_run_id,
            },
            source="nodeflow",
            user_id=ctx.user_id,
        ))

        return ExecutionResult(data={"notified": True, "title": title})


def _resolve(template: str, data: dict) -> str:
    """Simple {{input.key}} template resolution."""
    import re

    def replacer(m: re.Match) -> str:
        path = m.group(1).strip()
        if path.startswith("input."):
            return str(data.get(path[6:], m.group(0)))
        return m.group(0)

    return re.sub(r"\{\{(.+?)\}\}", replacer, template)
