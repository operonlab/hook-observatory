"""Ideagraph routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["ideagraph"])


@router.get("/status")
async def ideagraph_status():
    return {"module": "ideagraph", "status": "not_implemented"}
