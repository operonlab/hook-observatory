"""Notify executor — publishes a push notification via Redis Pub/Sub."""

import json
from typing import Any

from src.shared.redis import get_redis

from .base import BaseNodeExecutor, ExecutionContext, ExecutionResult

_PUSH_CHANNEL = "workshop:push"


class NotifyExecutor(BaseNodeExecutor):
    async def execute(
        self, config: dict[str, Any], ctx: ExecutionContext
    ) -> ExecutionResult:
        """Publish a notification to Redis workshop:push channel.

        The notification module's redis_push_listener picks this up and
        delivers it via Web Push to subscribed clients.

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

        payload = {
            "category": "nodeflow",
            "title": title,
            "body": message,
            "url": "/apps/nodeflow/",
            "tag": f"nodeflow-{ctx.flow_run_id}",
            "severity": level,
            "user_id": ctx.user_id,
        }

        r = get_redis()
        await r.publish(_PUSH_CHANNEL, json.dumps(payload, ensure_ascii=False))

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
