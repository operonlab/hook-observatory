"""Muse routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["muse"])


@router.get("/status")
async def muse_status():
    return {"module": "muse", "status": "not_implemented"}
