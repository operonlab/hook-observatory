"""Daily OS event handlers."""

from src.events.bus import event_bus
from src.events.types import DailyosEvents


@event_bus.on(DailyosEvents.PLAN_COMPLETED)
async def on_plan_completed(event):
    """Handle plan completion — placeholder for cross-module integration."""
    pass
