"""Taskflow module — task management with FSM status, scheduling, and progress tracking."""

from src.shared.grc_routes import create_grc_routes

from .grc_adapter import TaskflowGRCAdapter
from .routes import router

_grc_router = create_grc_routes(
    TaskflowGRCAdapter(),
    "taskflow",
    "taskflow.read",
    "taskflow.write",
)
router.include_router(_grc_router)

__all__ = ["router"]
