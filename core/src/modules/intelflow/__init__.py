"""Intelflow module — Smart Search V2, research reports, daily briefings, topic graph."""

from src.shared.grc_routes import create_grc_routes

from .grc_adapter import IntelflowGRCAdapter
from .routes import router

grc_router = create_grc_routes(
    IntelflowGRCAdapter(), "intelflow", "intelflow.read", "intelflow.write"
)
router.include_router(grc_router)
