"""Admin routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["admin"])


@router.get("/status")
async def admin_status():
    return {"module": "admin", "status": "not_implemented"}
