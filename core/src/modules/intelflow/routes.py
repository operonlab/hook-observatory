"""Intelflow routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["intelflow"])


@router.get("/status")
async def intelflow_status():
    return {"module": "intelflow", "status": "not_implemented"}
