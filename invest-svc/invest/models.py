"""Invest ORM models — accounts, positions, trades, quotes.

All tables live in the `invest` PostgreSQL schema.
All monetary columns use Numeric(15,4).
IDs: String(32) + uuid7().hex.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models import SpaceScopedModel

SCHEMA = "invest"


# ======================== Accounts ========================


class Account(SpaceScopedModel):
    """Investment account — brokerage, retirement, crypto, etc."""

    __tablename__ = "accounts"
    __table_args__ = (
        Index("idx_invest_account_space", "space_id"),
        Index(
            "idx_invest_account_unique_name",
            "space_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    broker: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    finance_wallet_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # bridge to finance.wallets (no FK — cross-schema)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    positions: Mapped[list["Position"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )


# ======================== Positions ========================


class Position(SpaceScopedModel):
    """A single holding — shares of a specific symbol in an account."""

    __tablename__ = "positions"
    __table_args__ = (
        Index("idx_position_account", "account_id"),
        Index(
            "idx_position_unique_symbol",
            "account_id",
            "symbol",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.accounts.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "2330.TW", "AAPL"
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. "TWSE", "NASDAQ"
    asset_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'stock'")
    )  # stock / etf / bond / crypto / fund
    shares: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    avg_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    current_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="position", cascade="all, delete-orphan", lazy="selectin"
    )


# ======================== Trades ========================


class Trade(SpaceScopedModel):
    """A buy/sell/dividend record for a position."""

    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trade_position", "position_id"),
        Index("idx_trade_space_time", "space_id", text("traded_at DESC")),
        {"schema": SCHEMA},
    )

    position_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.positions.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # buy / sell / dividend / split
    shares: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default=text("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default=text("0"))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    position: Mapped["Position"] = relationship(back_populates="trades")


# ======================== Quotes ========================


class Quote(SpaceScopedModel):
    """Price quote cache — manual or from external sources."""

    __tablename__ = "quotes"
    __table_args__ = (
        Index("idx_quote_symbol", "symbol"),
        Index(
            "idx_quote_unique_symbol_space",
            "space_id",
            "symbol",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual'")
    )  # manual / yahoo / fugle
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
