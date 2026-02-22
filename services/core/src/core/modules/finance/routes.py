"""Finance routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["finance"])


@router.get("/status")
async def finance_status():
    return {"module": "finance", "status": "not_implemented"}
