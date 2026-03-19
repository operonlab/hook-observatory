"""Taskflow event handlers."""

from src.events.bus import event_bus
from src.events.types import TaskflowEvents


async def on_task_completed(event):
    """Handle task completion — placeholder for cross-module integration."""
    pass


event_bus.channel(TaskflowEvents.TASK_COMPLETED).subscribe_handler(on_task_completed)
