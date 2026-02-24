"""Memvault routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["memvault"])


@router.get("/status")
async def memvault_status():
    return {"module": "memvault", "status": "not_implemented"}
