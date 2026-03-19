"""Invest services — CRUD + portfolio management + valuation.

This is the PUBLIC API of the invest module.
Other modules import from here, never from models.py.
"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import InvestEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.query_helpers import scoped_query
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import Account, Position, Quote, Trade
from .schemas import (
    AccountCreate,
    AccountResponse,
    AccountSummaryResponse,
    AccountUpdate,
    PortfolioSummaryResponse,
    PositionCreate,
    PositionPriceUpdate,
    PositionResponse,
    PositionUpdate,
    QuoteResponse,
    TradeCreate,
    TradeResponse,
    TradeUpdate,
)

# ======================== Helpers ========================


def _soft_delete_filter(query, model):
    """Exclude soft-deleted records."""
    if hasattr(model, "deleted_at"):
        return query.where(model.deleted_at == None)  # noqa: E711
    return query


def _calc_position_fields(pos: Position) -> dict:
    """Calculate derived fields for a position response."""
    market_value = pos.shares * pos.current_price
    total_cost = pos.shares * pos.avg_cost
    unrealized_gain = market_value - total_cost
    gain_pct = float(unrealized_gain / total_cost * 100) if total_cost else 0.0
    return {
        "market_value": market_value,
        "total_cost": total_cost,
        "unrealized_gain": unrealized_gain,
        "gain_pct": round(gain_pct, 2),
    }


# ======================== Account Service ========================


class AccountService(BaseCRUDService[Account, AccountCreate, AccountUpdate, AccountResponse]):
    model = Account
    audit_module = "invest"
    audit_entity_type = "accounts"

    def to_response(self, instance: Account) -> AccountResponse:
        return AccountResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            broker=instance.broker,
            currency=instance.currency,
            finance_wallet_id=instance.finance_wallet_id,
            notes=instance.notes,
            deleted_at=instance.deleted_at,
        )

    def to_summary_response(
        self, instance: Account, positions: Sequence[Position],
    ) -> AccountSummaryResponse:
        total_mv = Decimal("0")
        total_cost = Decimal("0")
        for pos in positions:
            total_mv += pos.shares * pos.current_price
            total_cost += pos.shares * pos.avg_cost
        total_gain = total_mv - total_cost
        gain_pct = float(total_gain / total_cost * 100) if total_cost else 0.0

        return AccountSummaryResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            broker=instance.broker,
            currency=instance.currency,
            finance_wallet_id=instance.finance_wallet_id,
            notes=instance.notes,
            deleted_at=instance.deleted_at,
            total_market_value=total_mv,
            total_cost=total_cost,
            total_gain=total_gain,
            gain_pct=round(gain_pct, 2),
            position_count=len(positions),
        )

    async def get_summary(self, db: AsyncSession, account_id: str) -> AccountSummaryResponse:
        account = await self.get(db, account_id)
        if not account:
            raise NotFoundError("Account not found", code="invest.account_not_found")

        q = select(Position).where(
            Position.account_id == account_id,
            Position.deleted_at == None,  # noqa: E711
        )
        positions: Sequence[Position] = (await db.execute(q)).scalars().all()
        return self.to_summary_response(account, positions)


# ======================== Position Service ========================


class PositionService(BaseCRUDService[Position, PositionCreate, PositionUpdate, PositionResponse]):
    model = Position
    audit_module = "invest"
    audit_entity_type = "positions"

    def to_response(self, instance: Position) -> PositionResponse:
        fields = _calc_position_fields(instance)
        return PositionResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            account_id=instance.account_id,
            symbol=instance.symbol,
            exchange=instance.exchange,
            asset_type=instance.asset_type,
            shares=instance.shares,
            avg_cost=instance.avg_cost,
            current_price=instance.current_price,
            currency=instance.currency,
            notes=instance.notes,
            deleted_at=instance.deleted_at,
            **fields,
        )

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        account_id: str | None = None,
    ) -> PaginatedResponse[PositionResponse]:
        p = pagination or PaginationParams()
        base = scoped_query(Position, space_id)
        if account_id:
            base = base.where(Position.account_id == account_id)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = base.order_by(Position.symbol).offset((p.page - 1) * p.page_size).limit(p.page_size)
        rows: Sequence[Position] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[PositionResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def update_price(
        self,
        db: AsyncSession,
        position_id: str,
        data: PositionPriceUpdate,
    ) -> Position:
        pos = await self.get(db, position_id)
        if not pos:
            raise NotFoundError("Position not found", code="invest.position_not_found")
        pos.current_price = data.price
        await db.flush()
        await db.refresh(pos)
        return pos


# ======================== Trade Service ========================


class TradeService(BaseCRUDService[Trade, TradeCreate, TradeUpdate, TradeResponse]):
    model = Trade
    audit_module = "invest"
    audit_entity_type = "trades"

    def to_response(self, instance: Trade) -> TradeResponse:
        total_amount = instance.shares * instance.price
        return TradeResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            position_id=instance.position_id,
            type=instance.type,
            shares=instance.shares,
            price=instance.price,
            fee=instance.fee,
            tax=instance.tax,
            currency=instance.currency,
            notes=instance.notes,
            traded_at=instance.traded_at,
            total_amount=total_amount,
            deleted_at=instance.deleted_at,
        )

    async def create(
        self, db: AsyncSession, space_id: str, data: TradeCreate, user_id: str | None = None
    ) -> Trade:
        # Validate position exists
        pos = await db.get(Position, data.position_id)
        if not pos or pos.deleted_at is not None:
            raise NotFoundError("Position not found", code="invest.position_not_found")

        # Create trade record
        trade = await super().create(db, space_id, data, user_id=user_id)

        # Update position shares and avg_cost based on trade type
        if data.type == "buy":
            new_total_cost = (pos.shares * pos.avg_cost) + (data.shares * data.price)
            new_shares = pos.shares + data.shares
            pos.avg_cost = new_total_cost / new_shares if new_shares else Decimal("0")
            pos.shares = new_shares
        elif data.type == "sell":
            if data.shares > pos.shares:
                raise BadRequestError(
                    "Cannot sell more shares than held",
                    code="invest.insufficient_shares",
                )
            pos.shares = pos.shares - data.shares
            if pos.shares == 0:
                pos.avg_cost = Decimal("0")
        elif data.type == "dividend":
            # Dividend doesn't change shares/avg_cost, just records income
            pass

        await db.flush()

        # Publish events
        event_type = InvestEvents.TRADE_EXECUTED
        if data.type == "dividend":
            event_type = InvestEvents.DIVIDEND_RECEIVED

        await event_bus.publish(Event(
            type=event_type,
            data={
                "trade_id": trade.id,
                "position_id": data.position_id,
                "symbol": pos.symbol,
                "type": data.type,
                "shares": str(data.shares),
                "price": str(data.price),
                "amount": str(data.shares * data.price),
            },
            source="invest",
            user_id=user_id,
        ))

        # Check if position was closed
        if pos.shares == 0:
            await event_bus.publish(Event(
                type=InvestEvents.POSITION_CLOSED,
                data={"position_id": data.position_id, "symbol": pos.symbol},
                source="invest",
                user_id=user_id,
            ))

        return trade

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        position_id: str | None = None,
    ) -> PaginatedResponse[TradeResponse]:
        p = pagination or PaginationParams()
        base = select(Trade).where(Trade.space_id == space_id)
        base = _soft_delete_filter(base, Trade)
        if position_id:
            base = base.where(Trade.position_id == position_id)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(Trade.traded_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[Trade] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[TradeResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Portfolio Service ========================


class PortfolioService:
    """Cross-account portfolio aggregation and valuation."""

    async def get_portfolio(self, db: AsyncSession, space_id: str) -> PortfolioSummaryResponse:
        # Get all active accounts
        acct_q = select(Account).where(Account.space_id == space_id)
        acct_q = _soft_delete_filter(acct_q, Account)
        accounts: Sequence[Account] = (await db.execute(acct_q)).scalars().all()

        total_mv = Decimal("0")
        total_cost = Decimal("0")
        position_count = 0
        account_summaries = []

        for acct in accounts:
            pos_q = select(Position).where(
                Position.account_id == acct.id,
                Position.deleted_at == None,  # noqa: E711
            )
            positions: Sequence[Position] = (await db.execute(pos_q)).scalars().all()
            summary = account_service.to_summary_response(acct, positions)
            account_summaries.append(summary)
            total_mv += summary.total_market_value
            total_cost += summary.total_cost
            position_count += summary.position_count

        total_gain = total_mv - total_cost
        gain_pct = float(total_gain / total_cost * 100) if total_cost else 0.0

        return PortfolioSummaryResponse(
            total_market_value=total_mv,
            total_cost=total_cost,
            total_gain=total_gain,
            gain_pct=round(gain_pct, 2),
            account_count=len(accounts),
            position_count=position_count,
            accounts=account_summaries,
        )

    async def refresh_quotes(
        self,
        db: AsyncSession,
        space_id: str,
        symbols: list[str] | None = None,
    ) -> list[QuoteResponse]:
        """Refresh quotes for all positions (or specific symbols).

        Phase 1: manual-only — just returns current quote records.
        Future: integrate Yahoo Finance / Fugle API.
        """
        base = select(Quote).where(Quote.space_id == space_id)
        base = _soft_delete_filter(base, Quote)
        if symbols:
            base = base.where(Quote.symbol.in_(symbols))
        rows: Sequence[Quote] = (await db.execute(base)).scalars().all()

        # Update position prices from quotes
        for quote in rows:
            await db.execute(
                update(Position)
                .where(
                    Position.space_id == space_id,
                    Position.symbol == quote.symbol,
                    Position.deleted_at == None,  # noqa: E711
                )
                .values(current_price=quote.price)
            )

        await db.flush()

        # Compute and publish total valuation update
        portfolio = await self.get_portfolio(db, space_id)

        await event_bus.publish(Event(
            type=InvestEvents.VALUATION_UPDATED,
            data={
                "space_id": space_id,
                "total_market_value": str(portfolio.total_market_value),
                "total_cost": str(portfolio.total_cost),
                "total_gain": str(portfolio.total_gain),
            },
            source="invest",
        ))

        return [
            QuoteResponse(
                id=q.id,
                space_id=q.space_id,
                created_by=q.created_by,
                created_at=q.created_at,
                updated_at=q.updated_at,
                symbol=q.symbol,
                price=q.price,
                prev_close=q.prev_close,
                change_pct=q.change_pct,
                currency=q.currency,
                source=q.source,
                quoted_at=q.quoted_at,
            )
            for q in rows
        ]


# ======================== Global Service Instances ========================

account_service = AccountService()
position_service = PositionService()
trade_service = TradeService()
portfolio_service = PortfolioService()
