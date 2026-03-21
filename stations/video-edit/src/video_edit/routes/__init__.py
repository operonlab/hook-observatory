"""Video Edit API routes."""

from fastapi import APIRouter

from video_edit.routes.projects import router as projects_router
from video_edit.routes.timeline import router as timeline_router
from video_edit.routes.effects import router as effects_router
from video_edit.routes.render import router as render_router

router = APIRouter()
router.include_router(projects_router, prefix="/projects", tags=["projects"])
router.include_router(timeline_router, tags=["timeline"])
router.include_router(effects_router, tags=["effects"])
router.include_router(render_router, tags=["render"])
