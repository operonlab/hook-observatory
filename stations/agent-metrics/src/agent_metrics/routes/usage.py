from fastapi import APIRouter
from agent_metrics.usage_collector import get_month_to_date, get_model_breakdown

router = APIRouter()

@router.get("/budget")
async def usage_budget():
    # 直接回傳拆分好的帳本
    return get_month_to_date()

@router.get("/by-model")
async def usage_by_model(days: int = 30):
    # 直接回傳拆分好的模型列表
    return get_model_breakdown(days)

# 補上空路由以防報錯
@router.get("/summary")
async def usage_summary(): return {}
@router.get("/trends")
async def usage_trends(): return {"daily": []}
@router.get("/subscription")
async def usage_subscription(): return {"providers": []}