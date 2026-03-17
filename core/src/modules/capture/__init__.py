"""Capture Pipeline — progressive enrichment for all modules."""

from fastapi import APIRouter

from src.shared.grc_routes import create_grc_routes

from .grc_adapter import CaptureGRCAdapter
from .routes import router as _capture_router

router = APIRouter()
router.include_router(_capture_router)

grc_router = create_grc_routes(
    CaptureGRCAdapter(),
    "capture",
    "capture.read",
    "capture.write",
)
router.include_router(grc_router)
