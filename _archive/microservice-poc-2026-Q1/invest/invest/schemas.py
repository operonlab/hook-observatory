"""Invest Pydantic schemas — request/response types.

All monetary fields use Decimal for precision.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from svc_shared.schemas import SpaceScopedResponse

# ======================== Account ========================


class AccountCreate(BaseModel):
    name: str
    broker: str | None = None
    currency: str = "TWD"
    finance_wallet_id: str | None = None
    notes: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    broker: str | None = None
    currency: str | None = None
    finance_wallet_id: str | None = None
    notes: str | None = None


class AccountResponse(SpaceScopedResponse):
    name: str
    broker: str | None = None
    currency: str
    finance_wallet_id: str | None = None
    notes: str | None = None
    deleted_at: datetime | None = None


class AccountSummaryResponse(AccountResponse):
    total_market_value: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_gain: Decimal = Decimal("0")
    gain_pct: float = 0.0
    position_count: int = 0


# ======================== Position ========================


class PositionCreate(BaseModel):
    account_id: str
    symbol: str
    exchange: str | None = None
    asset_type: str = "stock"
    shares: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")
    currency: str = "TWD"
    notes: str | None = None


class PositionUpdate(BaseModel):
    symbol: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    shares: Decimal | None = None
    avg_cost: Decimal | None = None
    current_price: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


class PositionResponse(SpaceScopedResponse):
    account_id: str
    symbol: str
    exchange: str | None = None
    asset_type: str
    shares: Decimal
    avg_cost: Decimal
    current_price: Decimal
    currency: str
    notes: str | None = None
    market_value: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    unrealized_gain: Decimal = Decimal("0")
    gain_pct: float = 0.0
    deleted_at: datetime | None = None


class PositionPriceUpdate(BaseModel):
    price: Decimal


# ======================== Trade ========================


class TradeCreate(BaseModel):
    position_id: str
    type: str  # buy / sell / dividend / split
    shares: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    currency: str = "TWD"
    notes: str | None = None
    traded_at: datetime


class TradeUpdate(BaseModel):
    type: str | None = None
    shares: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal | None = None
    tax: Decimal | None = None
    notes: str | None = None
    traded_at: datetime | None = None


class TradeResponse(SpaceScopedResponse):
    position_id: str
    type: str
    shares: Decimal
    price: Decimal
    fee: Decimal
    tax: Decimal
    currency: str
    notes: str | None = None
    traded_at: datetime
    total_amount: Decimal = Decimal("0")
    deleted_at: datetime | None = None


# ======================== Quote ========================


class QuoteResponse(SpaceScopedResponse):
    symbol: str
    price: Decimal
    prev_close: Decimal | None = None
    change_pct: Decimal | None = None
    currency: str
    source: str
    quoted_at: datetime


class QuoteRefreshRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


# ======================== Portfolio ========================


class PortfolioSummaryResponse(BaseModel):
    total_market_value: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_gain: Decimal = Decimal("0")
    gain_pct: float = 0.0
    account_count: int = 0
    position_count: int = 0
    accounts: list[AccountSummaryResponse] = Field(default_factory=list)


class AssetAllocationItem(BaseModel):
    asset_type: str
    market_value: Decimal = Decimal("0")
    pct: float = 0.0
    count: int = 0
