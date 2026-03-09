"""Finance ORM models — transactions, categories, wallets, subscriptions,
installment plans, budgets, tags, attachments, snapshots.

All tables live in the `finance` PostgreSQL schema.
All monetary columns use Numeric(15,4).
IDs: String(32) + uuid7().hex.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import Base, SpaceScopedModel

SCHEMA = "finance"


# ======================== Wallets ========================


class Wallet(SpaceScopedModel):
    """Multi-account balance management — bank, credit card, cash, e-wallet, investment."""

    __tablename__ = "wallets"
    __table_args__ = (
        Index("idx_wallet_space", "space_id"),
        Index(
            "idx_wallet_unique_name",
            "space_id",
            "name",
            unique=True,
            postgresql_where=text("is_active = true AND deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # bank_account / credit_card / cash / e_wallet / investment
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    initial_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    current_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sync_provider: Mapped[str] = mapped_column(Text, server_default=text("'manual'"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # deleted_at inherited from SoftDeleteMixin via SpaceScopedModel


# ======================== Categories ========================


class Category(SpaceScopedModel):
    """Tree-structured transaction categories with parent_id self-reference."""

    __tablename__ = "categories"
    __table_args__ = (
        Index(
            "idx_category_unique_name",
            "space_id",
            text("COALESCE(parent_id, '')"),
            "name",
            unique=True,
            postgresql_where=text("is_active = true AND deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Relationships
    children: Mapped[list["Category"]] = relationship(
        "Category",
        back_populates="parent",
        lazy="selectin",
    )
    parent: Mapped["Category | None"] = relationship(
        "Category",
        back_populates="children",
        remote_side="Category.id",
        lazy="selectin",
    )


# ======================== Installment Plans ========================


class InstallmentPlan(SpaceScopedModel):
    """Installment payment tracking — generates N scheduled transactions."""

    __tablename__ = "installment_plans"
    __table_args__ = ({"schema": SCHEMA},)

    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    num_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default=text("0"))
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_type: Mapped[str] = mapped_column(
        Text, server_default=text("'none'")
    )  # none/interest/fee_per_period/total_fee
    fee_per_installment: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default=text("0"))
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.categories.id", ondelete="SET NULL"), nullable=True
    )
    wallet_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.wallets.id", ondelete="RESTRICT"), nullable=False
    )
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    payment_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'active'")
    )  # active/completed/cancelled
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), default=list
    )
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# ======================== Transactions ========================


class Transaction(SpaceScopedModel):
    """A single financial transaction — income, expense, or transfer."""

    __tablename__ = "transactions"
    __table_args__ = (
        Index("idx_txn_space_time", "space_id", text("transacted_at DESC")),
        Index("idx_txn_wallet", "wallet_id"),
        Index("idx_txn_category", "space_id", "category_id", text("transacted_at")),
        Index("idx_txn_installment", "installment_plan_id"),
        Index(
            "idx_txn_installment_num",
            "installment_plan_id",
            "installment_number",
            unique=True,
            postgresql_where=text("installment_plan_id IS NOT NULL"),
        ),
        Index(
            "idx_txn_scheduled",
            "status",
            text("transacted_at"),
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index(
            "idx_txn_paired",
            "paired_transaction_id",
            postgresql_where=text("paired_transaction_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # income/expense/transfer
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    payment_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.categories.id", ondelete="SET NULL"), nullable=True
    )
    wallet_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.wallets.id", ondelete="RESTRICT"), nullable=False
    )
    transfer_to_wallet_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.wallets.id", ondelete="RESTRICT"), nullable=True
    )
    installment_plan_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.installment_plans.id", ondelete="SET NULL"), nullable=True
    )
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paired_transaction_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.transactions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'completed'")
    )  # completed/scheduled/cancelled/pending
    settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default=text("0"))
    invoice_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    transacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    tags: Mapped[list["TransactionTag"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )
    attachments: Mapped[list["TransactionAttachment"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )


# ======================== Transaction Tags ========================


class TransactionTag(Base):
    """M2M tag for a transaction."""

    __tablename__ = "transaction_tags"
    __table_args__ = ({"schema": SCHEMA},)

    transaction_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)

    transaction: Mapped["Transaction"] = relationship(back_populates="tags")


# ======================== Transaction Attachments ========================


class TransactionAttachment(Base):
    """Receipt photo stored in RustFS (S3-compatible)."""

    __tablename__ = "transaction_attachments"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.transactions.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(back_populates="attachments")


# ======================== Subscriptions ========================


class Subscription(SpaceScopedModel):
    """Recurring billing — monthly, yearly, weekly."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_sub_space", "space_id"),
        {"schema": SCHEMA},
    )

    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'TWD'"))
    billing_cycle: Mapped[str] = mapped_column(Text, nullable=False)  # monthly/yearly/weekly
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.categories.id", ondelete="SET NULL"), nullable=True
    )
    wallet_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.wallets.id", ondelete="SET NULL"), nullable=True
    )
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'active'")
    )  # active/paused/cancelled
    next_billing: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), default=list
    )
    reminder_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# ======================== Wallet Snapshots ========================


class WalletSnapshot(SpaceScopedModel):
    """Balance reconciliation snapshot — synced vs calculated balance."""

    __tablename__ = "wallet_snapshots"
    __table_args__ = (
        Index("idx_snapshot_wallet_time", "wallet_id", text("synced_at DESC")),
        Index("idx_snapshot_space_time", "space_id", text("synced_at DESC")),
        {"schema": SCHEMA},
    )

    wallet_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.wallets.id", ondelete="CASCADE"), nullable=False
    )
    synced_balance: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    calculated_balance: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    difference: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), Computed("synced_balance - calculated_balance", persisted=True)
    )
    snapshot_type: Mapped[str] = mapped_column(
        Text, server_default=text("'reconciliation'")
    )  # reconciliation/valuation
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ======================== Budgets ========================


class Budget(SpaceScopedModel):
    """Monthly budget — total or per-category."""

    __tablename__ = "budgets"
    __table_args__ = (
        Index(
            "idx_budget_with_category",
            "space_id",
            "year_month",
            "category_id",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "idx_budget_total",
            "space_id",
            "year_month",
            unique=True,
            postgresql_where=text("category_id IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    year_month: Mapped[str] = mapped_column(Text, nullable=False)  # '2026-03'
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.categories.id", ondelete="CASCADE"), nullable=True
    )
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    savings_target: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# ======================== Tag Styles ========================


class TagStyle(SpaceScopedModel):
    """Per-space tag color mapping stored as JSONB."""

    __tablename__ = "tag_styles"
    __table_args__ = (
        Index("idx_tag_styles_space", "space_id", unique=True),
        {"schema": SCHEMA},
    )

    styles: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), default=dict)
