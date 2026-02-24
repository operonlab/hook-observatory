"""Skillpath routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["skillpath"])


@router.get("/status")
async def skillpath_status():
    return {"module": "skillpath", "status": "not_implemented"}
