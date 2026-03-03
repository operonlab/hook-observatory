"""Agent Metrics API routes — dispatch + projects + metrics + usage + sysmon."""

from fastapi import APIRouter

from agent_metrics.routes.dispatch import router as dispatch_router
from agent_metrics.routes.metrics import router as metrics_router
from agent_metrics.routes.projects import router as projects_router
from agent_metrics.routes.sysmon import router as sysmon_router
from agent_metrics.routes.usage import router as usage_router

router = APIRouter()
router.include_router(dispatch_router, prefix="/maestro", tags=["maestro"])
router.include_router(projects_router, prefix="/projects", tags=["projects"])
router.include_router(metrics_router, tags=["metrics"])
router.include_router(usage_router, prefix="/usage", tags=["usage"])
router.include_router(sysmon_router, tags=["sysmon"])
