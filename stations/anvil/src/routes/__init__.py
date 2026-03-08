"""Combined API router for Anvil Station."""

from __future__ import annotations

from fastapi import APIRouter

from routes.corrections import router as corrections_router
from routes.evaluations import router as evaluations_router
from routes.health import router as health_router
from routes.invocations import router as invocations_router
from routes.lifecycle import router as lifecycle_router
from routes.skills import router as skills_router
from routes.stats import router as stats_router

router = APIRouter(prefix="/api/anvil")

router.include_router(health_router, tags=["health"])
router.include_router(skills_router, tags=["skills"])
router.include_router(invocations_router, tags=["invocations"])
router.include_router(stats_router, tags=["stats"])
router.include_router(evaluations_router, tags=["evaluations"])
router.include_router(corrections_router, tags=["corrections"])
router.include_router(lifecycle_router, tags=["lifecycle"])
