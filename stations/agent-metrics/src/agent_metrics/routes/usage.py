from fastapi import APIRouter
from agent_metrics.usage_collector import get_month_to_date, get_model_breakdown, get_today_cost

router = APIRouter()


@router.get("/budget")
async def usage_budget():
    return get_month_to_date()


@router.get("/by-model")
async def usage_by_model(days: int = 30):
    return get_model_breakdown(days)


@router.get("/daily-cost")
async def daily_cost():
    return get_today_cost()


@router.get("/summary")
async def usage_summary():
    return {}


@router.get("/trends")
async def usage_trends():
    return {"daily": []}


@router.get("/subscription")
async def usage_subscription():
    return {"providers": []}
