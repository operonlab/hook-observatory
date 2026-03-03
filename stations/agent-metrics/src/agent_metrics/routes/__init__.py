"""Agent Metrics API routes — dispatch + projects + metrics."""

from fastapi import APIRouter

from agent_metrics.routes.dispatch import router as dispatch_router
from agent_metrics.routes.metrics import router as metrics_router
from agent_metrics.routes.projects import router as projects_router

router = APIRouter()
router.include_router(dispatch_router, prefix="/maestro", tags=["maestro"])
router.include_router(projects_router, prefix="/projects", tags=["projects"])
router.include_router(metrics_router, tags=["metrics"])
