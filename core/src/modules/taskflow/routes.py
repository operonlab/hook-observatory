"""Taskflow routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["taskflow"])


@router.get("/status")
async def taskflow_status():
    return {"module": "taskflow", "status": "not_implemented"}
