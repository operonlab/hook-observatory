"""Workpool routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["workpool"])


@router.get("/status")
async def workpool_status():
    return {"module": "workpool", "status": "not_implemented"}
