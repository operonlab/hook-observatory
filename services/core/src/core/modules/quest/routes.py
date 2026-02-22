"""Quest routes — placeholder."""

from fastapi import APIRouter

router = APIRouter(tags=["quest"])


@router.get("/status")
async def quest_status():
    return {"module": "quest", "status": "not_implemented"}
