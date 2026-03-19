"""Finance Pydantic schemas — request/response types.

All monetary fields use Decimal for precision.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== Wallet ========================


class WalletCreate(BaseModel):
    name: str
    type: str  # bank_account / credit_card / cash / e_wallet / investment
    currency: str = "TWD"
    initial_balance: Decimal = Decimal("0")
    credit_limit: Decimal | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    is_private: bool = False


class WalletUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    currency: str | None = None
    credit_limit: Decimal | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    is_private: bool | None = None
    sync_provider: str | None = None


class WalletResponse(SpaceScopedResponse):
    name: str
    type: str
    currency: str
    initial_balance: Decimal
    current_balance: Decimal
    credit_limit: Decimal | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    is_active: bool = True
    is_private: bool = False
    sync_provider: str = "manual"
    last_synced_at: datetime | None = None
    deleted_at: datetime | None = None


# ======================== Category ========================


class CategoryCreate(BaseModel):
    name: str
    parent_id: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    is_private: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    is_private: bool | None = None


class CategoryResponse(SpaceScopedResponse):
    name: str
    parent_id: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    is_active: bool = True
    is_private: bool = False
    children: list["CategoryResponse"] = Field(default_factory=list)


# ======================== Installment Plan ========================


class InstallmentPlanCreate(BaseModel):
    icon_url: str | None = None
    description: str
    total_amount: Decimal
    currency: str = "TWD"
    num_installments: int
    installment_amount: Decimal
    interest_rate: Decimal = Decimal("0")
    billing_day: int | None = None
    fee_type: str = "none"
    fee_per_installment: Decimal = Decimal("0")
    merchant: str | None = None
    category_id: str | None = None
    wallet_id: str
    payment_method: str
    payment_detail: str | None = None
    start_date: date
    end_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    is_private: bool = False


class InstallmentPlanUpdate(BaseModel):
    icon_url: str | None = None
    description: str | None = None
    billing_day: int | None = None
    merchant: str | None = None
    category_id: str | None = None
    payment_detail: str | None = None
    end_date: date | None = None
    status: str | None = None
    tags: list[str] | None = None
    is_private: bool | None = None


class InstallmentPlanResponse(SpaceScopedResponse):
    icon_url: str | None = None
    description: str
    total_amount: Decimal
    currency: str
    num_installments: int
    installment_amount: Decimal
    interest_rate: Decimal
    billing_day: int | None = None
    fee_type: str = "none"
    fee_per_installment: Decimal
    merchant: str | None = None
    category_id: str | None = None
    wallet_id: str
    payment_method: str
    payment_detail: str | None = None
    start_date: date
    end_date: date | None = None
    status: str = "active"
    tags: list[str] = Field(default_factory=list)
    is_private: bool = False


# ======================== Transaction ========================


class TransactionCreate(BaseModel):
    icon_url: str | None = None
    type: str  # income / expense / transfer
    amount: Decimal
    currency: str = "TWD"
    description: str | None = None
    merchant: str | None = None
    payment_method: str
    payment_detail: str | None = None
    category_id: str | None = None
    wallet_id: str
    transfer_to_wallet_id: str | None = None
    installment_plan_id: str | None = None
    installment_number: int | None = None
    status: str = "completed"
    settlement_amount: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    fee: Decimal = Decimal("0")
    invoice_number: str | None = None
    is_private: bool = False
    transacted_at: datetime
    tags: list[str] = Field(default_factory=list)


class TransactionUpdate(BaseModel):
    icon_url: str | None = None
    type: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    description: str | None = None
    merchant: str | None = None
    payment_method: str | None = None
    payment_detail: str | None = None
    category_id: str | None = None
    status: str | None = None
    settlement_amount: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    fee: Decimal | None = None
    invoice_number: str | None = None
    is_private: bool | None = None
    transacted_at: datetime | None = None
    tags: list[str] | None = None


class TransactionResponse(SpaceScopedResponse):
    icon_url: str | None = None
    type: str
    amount: Decimal
    currency: str
    description: str | None = None
    merchant: str | None = None
    payment_method: str
    payment_detail: str | None = None
    category_id: str | None = None
    wallet_id: str
    transfer_to_wallet_id: str | None = None
    installment_plan_id: str | None = None
    installment_number: int | None = None
    paired_transaction_id: str | None = None
    status: str = "completed"
    settlement_amount: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    fee: Decimal = Decimal("0")
    invoice_number: str | None = None
    is_private: bool = False
    transacted_at: datetime
    tags: list[str] = Field(default_factory=list)


# ======================== Subscription ========================


class SubscriptionCreate(BaseModel):
    icon_url: str | None = None
    name: str
    amount: Decimal
    currency: str = "TWD"
    billing_cycle: str  # monthly / yearly / weekly
    billing_day: int | None = None
    category_id: str | None = None
    wallet_id: str | None = None
    payment_method: str | None = None
    payment_detail: str | None = None
    start_date: date
    end_date: date | None = None
    next_billing: date | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    reminder_days: int | None = None
    is_private: bool = False


class SubscriptionUpdate(BaseModel):
    icon_url: str | None = None
    name: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    billing_cycle: str | None = None
    billing_day: int | None = None
    category_id: str | None = None
    wallet_id: str | None = None
    payment_method: str | None = None
    payment_detail: str | None = None
    end_date: date | None = None
    status: str | None = None
    next_billing: date | None = None
    notes: str | None = None
    tags: list[str] | None = None
    reminder_days: int | None = None
    is_private: bool | None = None


class SubscriptionResponse(SpaceScopedResponse):
    icon_url: str | None = None
    name: str
    amount: Decimal
    currency: str
    billing_cycle: str
    billing_day: int | None = None
    category_id: str | None = None
    wallet_id: str | None = None
    payment_method: str | None = None
    payment_detail: str | None = None
    start_date: date
    end_date: date | None = None
    status: str = "active"
    next_billing: date | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    reminder_days: int | None = None
    is_private: bool = False


# ======================== Budget ========================


class BudgetCreate(BaseModel):
    year_month: str  # '2026-03'
    category_id: str | None = None
    budget_amount: Decimal
    savings_target: Decimal | None = None
    is_private: bool = False


class BudgetUpdate(BaseModel):
    budget_amount: Decimal | None = None
    savings_target: Decimal | None = None
    is_private: bool | None = None


class BudgetResponse(SpaceScopedResponse):
    year_month: str
    category_id: str | None = None
    category_name: str | None = None
    budget_amount: Decimal
    savings_target: Decimal | None = None
    spent_amount: Decimal = Decimal("0")
    remaining_amount: Decimal = Decimal("0")
    used_pct: float = 0.0
    is_private: bool = False


# ======================== Wallet Snapshot ========================


class WalletSnapshotResponse(SpaceScopedResponse):
    wallet_id: str
    synced_balance: Decimal
    calculated_balance: Decimal
    difference: Decimal
    snapshot_type: str = "reconciliation"
    notes: str | None = None
    synced_at: datetime
    version: int = 0
    batch_id: str | None = None
    metadata_json: dict | None = None


class SnapshotDiffResponse(BaseModel):
    wallet_id: str
    from_version: int
    to_version: int
    from_synced_balance: Decimal
    to_synced_balance: Decimal
    balance_delta: Decimal
    delta_pct: float
    from_synced_at: datetime
    to_synced_at: datetime
    period_days: int


class GapAnalysisResponse(BaseModel):
    wallet_id: str
    from_version: int
    to_version: int
    snapshot_delta: Decimal
    transaction_sum: Decimal
    gap: Decimal
    gap_pct: float
    is_reconciled: bool
    transactions: list[TransactionResponse]
    from_synced_at: datetime
    to_synced_at: datetime


class GlobalSnapshotResponse(BaseModel):
    batch_id: str
    snapshot_count: int
    total_net_worth: Decimal
    snapshots: list[WalletSnapshotResponse]
    created_at: datetime


class GlobalSnapshotSummary(BaseModel):
    batch_id: str
    snapshot_count: int
    total_net_worth: Decimal
    created_at: datetime


# ======================== Transfer ========================


class TransferRequest(BaseModel):
    from_wallet_id: str
    to_wallet_id: str
    amount: Decimal
    currency: str = "TWD"
    description: str | None = None
    payment_method: str = "bank_transfer"
    payment_detail: str | None = None
    fee: Decimal = Decimal("0")
    transacted_at: datetime


# ======================== Wallet Sync ========================


class WalletSyncRequest(BaseModel):
    synced_balance: Decimal
    notes: str | None = None


class ReconcileResponse(BaseModel):
    wallet_id: str
    wallet_name: str
    current_balance: Decimal
    calculated_balance: Decimal
    difference: Decimal
    transaction_count: int
    last_synced_at: datetime | None = None


# ======================== Exchange Rate ========================


class ExchangeRateResponse(BaseModel):
    base: str = "USD"
    rates: dict[str, float] = Field(default_factory=dict)
    date: str = ""


# ======================== Summary ========================


class CategoryBreakdown(BaseModel):
    category_id: str | None = None
    category_name: str = "未分類"
    category_icon: str | None = None
    amount: Decimal = Decimal("0")
    pct: float = 0.0
    count: int = 0


class WalletOverviewItem(BaseModel):
    wallet_id: str
    wallet_name: str
    wallet_type: str
    current_balance: Decimal
    change: Decimal = Decimal("0")


class MonthlySummaryResponse(BaseModel):
    year_month: str
    total_income: Decimal = Decimal("0")
    total_expense: Decimal = Decimal("0")
    net: Decimal = Decimal("0")
    transaction_count: int = 0
    category_breakdown: list[CategoryBreakdown] = []
    wallet_overview: list[WalletOverviewItem] = []


class MonthlyTrendResponse(BaseModel):
    year_month: str
    income: Decimal = Decimal("0")
    expense: Decimal = Decimal("0")
    net: Decimal = Decimal("0")


class NetWorthPointResponse(BaseModel):
    date: str
    total: Decimal = Decimal("0")
    bank: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")
    e_wallet: Decimal = Decimal("0")
    investment: Decimal = Decimal("0")
    credit_card: Decimal = Decimal("0")


# ======================== Search ========================


class FinanceSearchResult(BaseModel):
    entity_type: str  # "transaction" or "subscription"
    entity_id: str
    score: float
    content_preview: str
    metadata: dict = Field(default_factory=dict)


# ======================== Tag Styles ========================


class TagStylesUpdate(BaseModel):
    styles: dict[str, str]  # {tag_name: color_hex}


class TagStylesResponse(BaseModel):
    styles: dict[str, str] = Field(default_factory=dict)
