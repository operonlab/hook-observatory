"""AgentOps API routes — dispatch + projects."""

from fastapi import APIRouter

from agentops.routes.dispatch import router as dispatch_router
from agentops.routes.projects import router as projects_router

router = APIRouter()
router.include_router(dispatch_router, prefix="/maestro", tags=["maestro"])
router.include_router(projects_router, prefix="/projects", tags=["projects"])
