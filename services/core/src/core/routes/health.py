"""Health check routes — self check."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "core"
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# GET /health — core self check
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="healthy")
