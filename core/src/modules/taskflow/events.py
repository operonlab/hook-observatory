"""Taskflow event handlers."""

from src.events.bus import event_bus
from src.events.types import TaskflowEvents


@event_bus.on(TaskflowEvents.TASK_COMPLETED)
async def on_task_completed(event):
    """Handle task completion — placeholder for cross-module integration."""
    pass
