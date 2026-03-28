"""Invest routes — REST API endpoints for standalone invest-svc.

Simplified from core/src/modules/invest/routes.py:
- No auth middleware (standalone service, auth handled at gateway)
- No EventBus (no cross-module event publishing)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from svc_shared.database import get_db
from svc_shared.errors import NotFoundError
from svc_shared.schemas import PaginatedResponse, PaginationParams

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
):
    return await account_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
    )


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    instance = await account_service.get(db, account_id)
    if not instance:
        raise NotFoundError("Account not found", code="invest.account_not_found")
    return account_service.to_response(instance)


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    data: AccountCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await account_service.create(db, space_id, data)
    await db.commit()
    return account_service.to_response(instance)


@router.put("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
):
    instance = await account_service.update(db, account_id, data)
    if not instance:
        raise NotFoundError("Account not found", code="invest.account_not_found")
    await db.commit()
    return account_service.to_response(instance)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await account_service.delete(db, account_id)
    if not deleted:
        raise NotFoundError("Account not found", code="invest.account_not_found")
    await db.commit()


@router.get("/accounts/{account_id}/summary", response_model=AccountSummaryResponse)
async def get_account_summary(
    account_id: str,
    db: AsyncSession = Depends(get_db),
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
):
    instance = await position_service.create(db, space_id, data)
    await db.commit()
    return position_service.to_response(instance)


@router.put("/positions/{position_id}/price", response_model=PositionResponse)
async def update_position_price(
    position_id: str,
    data: PositionPriceUpdate,
    db: AsyncSession = Depends(get_db),
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
):
    instance = await trade_service.create(db, space_id, data)
    await db.commit()
    return trade_service.to_response(instance)


# ======================== Portfolio ========================


@router.get("/portfolio", response_model=PortfolioSummaryResponse)
async def get_portfolio(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await portfolio_service.get_portfolio(db, space_id)


@router.post("/quotes/refresh", response_model=list[QuoteResponse])
async def refresh_quotes(
    data: QuoteRefreshRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await portfolio_service.refresh_quotes(
        db, space_id, symbols=data.symbols if data.symbols else None
    )
    await db.commit()
    return result


# ======================== Status ========================


@router.get("/status")
async def invest_status():
    return {"module": "invest", "status": "active", "service": "invest-svc"}
