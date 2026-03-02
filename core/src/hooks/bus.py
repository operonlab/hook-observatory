"""Hook Bus — before/after lifecycle hooks for plugins."""

from collections.abc import Callable, Coroutine
from typing import Any

Handler = Callable[..., Coroutine[Any, Any, Any]]


class HookBus:
    def __init__(self):
        self._hooks: dict[str, list[Handler]] = {}
        self._plugins: dict[str, dict] = {}

    def register(self, hook_name: str, handler: Handler, plugin_id: str = "core"):
        self._hooks.setdefault(hook_name, []).append(handler)

    async def trigger(self, hook_name: str, context: dict[str, Any]) -> dict[str, Any]:
        handlers = self._hooks.get(hook_name, [])
        for handler in handlers:
            result = await handler(context)
            if isinstance(result, dict):
                context.update(result)
        return context

    async def load_plugins(self, plugin_dir: str):
        # Future: scan plugin_dir for plugin.json manifests
        pass


hook_bus = HookBus()
