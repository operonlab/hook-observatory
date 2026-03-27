"""Node health monitoring and capability-based selection."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from remote_tmux import RemoteTmux

logger = logging.getLogger(__name__)


@dataclass
class NodeState:
    name: str
    config: dict
    remote_tmux: RemoteTmux
    healthy: bool = False
    last_check: float = 0
    active_tasks: int = 0
    last_error: str = ""

    @property
    def capabilities(self) -> list[str]:
        return self.config.get("capabilities", [])

    @property
    def platform(self) -> str:
        return self.config.get("platform", "unknown")


class NodeRegistry:
    """Manages node health and capability-based task routing."""

    def __init__(self, nodes_config: dict):
        self._nodes: dict[str, NodeState] = {}
        for name, cfg in nodes_config.items():
            ssh_cmd = cfg.get("ssh_command")
            rt = RemoteTmux(ssh_command=ssh_cmd, node_name=name)
            self._nodes[name] = NodeState(name=name, config=cfg, remote_tmux=rt)

    def get(self, name: str) -> NodeState | None:
        return self._nodes.get(name)

    def all_nodes(self) -> list[NodeState]:
        return list(self._nodes.values())

    def healthy_nodes(self) -> list[NodeState]:
        return [n for n in self._nodes.values() if n.healthy]

    def select_node(self, capabilities: list[str] | None = None) -> NodeState | None:
        """Select the best node: filter by capability, sort by load (fewest active tasks)."""
        candidates = self.healthy_nodes()
        if capabilities:
            candidates = [
                n for n in candidates if all(cap in n.capabilities for cap in capabilities)
            ]
        if not candidates:
            return None
        # Sort by active_tasks ascending (least loaded first)
        candidates.sort(key=lambda n: n.active_tasks)
        return candidates[0]

    async def check_node(self, name: str) -> bool:
        """Run a single health check on a node."""
        node = self._nodes.get(name)
        if not node:
            return False
        loop = asyncio.get_event_loop()
        healthy = await loop.run_in_executor(None, node.remote_tmux.ping)
        node.healthy = healthy
        node.last_check = time.time()
        if not healthy:
            node.last_error = "ping failed"
        else:
            node.last_error = ""
        return healthy

    async def health_check_loop(self, interval: int = 30):
        """Background task: periodically check all nodes."""
        while True:
            for name in list(self._nodes):
                try:
                    await self.check_node(name)
                except Exception as e:
                    logger.error("Health check failed for %s: %s", name, e)
            await asyncio.sleep(interval)

    def to_dict(self) -> list[dict]:
        """Serialize all nodes for API response."""
        return [
            {
                "name": n.name,
                "healthy": n.healthy,
                "active_tasks": n.active_tasks,
                "capabilities": n.capabilities,
                "platform": n.platform,
                "last_check": n.last_check,
                "last_error": n.last_error,
                "gpu": n.config.get("gpu"),
            }
            for n in self._nodes.values()
        ]
