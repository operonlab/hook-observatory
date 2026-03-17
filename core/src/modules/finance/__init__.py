"""Finance module — transactions, budgets, subscriptions, wallets."""

from fastapi import APIRouter

from src.shared.grc_routes import create_grc_routes

from .grc_adapter import FinanceGRCAdapter
from .routes import router as _finance_router

router = APIRouter()
router.include_router(_finance_router)

grc_router = create_grc_routes(
    FinanceGRCAdapter(),
    "finance",
    "finance.read",
    "finance.write",
)
router.include_router(grc_router)
