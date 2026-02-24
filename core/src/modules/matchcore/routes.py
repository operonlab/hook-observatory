"""Matchcore routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["matchcore"])


@router.get("/status")
async def matchcore_status():
    return {"module": "matchcore", "status": "not_implemented"}
