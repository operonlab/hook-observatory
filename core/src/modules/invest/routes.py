"""Invest routes — REST API endpoints.

Prefix: /api/invest (mounted in main.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    AccountCreate,
    AccountResponse,
    AccountSummaryResponse,
    AccountUpdate,
    PortfolioSummaryResponse,
    PositionCreate,
    PositionPriceUpdate,
    PositionResponse,
    QuoteRefreshRequest,
    QuoteResponse,
    TradeCreate,
    TradeResponse,
)
from .services import (
    account_service,
    portfolio_service,
    position_service,
    trade_service,
)

router = APIRouter(tags=["invest"])


# ======================== Accounts ========================


@router.get("/accounts", response_model=PaginatedResponse[AccountResponse])
async def list_accounts(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    return await account_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
    )


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    instance = await account_service.get_in_space(db, account_id, space_id)
    if not instance:
        raise NotFoundError("Account not found", code="invest.account_not_found")
    return account_service.to_response(instance)


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    data: AccountCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    instance = await account_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return account_service.to_response(instance)


@router.put("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    data: AccountUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    instance = await account_service.update(
        db, account_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Account not found", code="invest.account_not_found")
    await db.commit()
    return account_service.to_response(instance)


@router.get("/accounts/{account_id}/summary", response_model=AccountSummaryResponse)
async def get_account_summary(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    return await account_service.get_summary(db, account_id)


# ======================== Positions ========================


@router.get("/positions", response_model=PaginatedResponse[PositionResponse])
async def list_positions(
    space_id: str = Query("default"),
    account_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    return await position_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        account_id=account_id,
    )


@router.post("/positions", response_model=PositionResponse, status_code=201)
async def create_position(
    data: PositionCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    instance = await position_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return position_service.to_response(instance)


@router.put("/positions/{position_id}/price", response_model=PositionResponse)
async def update_position_price(
    position_id: str,
    data: PositionPriceUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    instance = await position_service.update_price(db, position_id, data)
    await db.commit()
    return position_service.to_response(instance)


# ======================== Trades ========================


@router.get("/trades", response_model=PaginatedResponse[TradeResponse])
async def list_trades(
    space_id: str = Query("default"),
    position_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    return await trade_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        position_id=position_id,
    )


@router.post("/trades", response_model=TradeResponse, status_code=201)
async def create_trade(
    data: TradeCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    instance = await trade_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return trade_service.to_response(instance)


# ======================== Portfolio ========================


@router.get("/portfolio", response_model=PortfolioSummaryResponse)
async def get_portfolio(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.read"),
):
    return await portfolio_service.get_portfolio(db, space_id)


@router.post("/quotes/refresh", response_model=list[QuoteResponse])
async def refresh_quotes(
    data: QuoteRefreshRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("invest.write"),
):
    result = await portfolio_service.refresh_quotes(
        db, space_id, symbols=data.symbols if data.symbols else None
    )
    await db.commit()
    return result
