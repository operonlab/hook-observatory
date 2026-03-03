"""Comprehensive tests for the Finance module.

Tests cover:
- Schema validation (Pydantic models)
- Helper functions (_balance_delta, _next_billing_date)
- Service layer (CRUD, privacy filter, wallet balance, transfers, budgets)
- Cron jobs (installment due, subscription billing, idempotency)
- Route layer (endpoints via ASGI test client)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import ValidationError

# --- Cron ---
from src.modules.finance.cron import (
    _next_billing_date,
    process_installment_due,
    process_subscription_billing,
    run_all_cron,
)

# --- Models ---
from src.modules.finance.models import (
    Budget,
    Category,
    InstallmentPlan,
    Subscription,
    Transaction,
    Wallet,
)

# --- Schemas ---
from src.modules.finance.schemas import (
    BudgetCreate,
    BudgetResponse,
    CategoryBreakdown,
    CategoryCreate,
    CategoryResponse,
    InstallmentPlanCreate,
    MonthlySummaryResponse,
    ReconcileResponse,
    SubscriptionCreate,
    TransactionCreate,
    TransactionResponse,
    TransferRequest,
    WalletCreate,
    WalletResponse,
    WalletSyncRequest,
    WalletUpdate,
)

# --- Services ---
from src.modules.finance.services import (
    BudgetService,
    TransactionService,
    _balance_delta,
    apply_privacy_filter,
    budget_service,
    category_service,
    summary_service,
    transaction_service,
    transfer_service,
    wallet_service,
)

# --- Shared ---
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse
from uuid_utils import uuid7

# ==================== Fixtures ====================


@pytest.fixture
def mock_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_wallet():
    """Create a sample Wallet instance for testing."""
    w = MagicMock(spec=Wallet)
    w.id = uuid7().hex
    w.space_id = "test-space"
    w.created_by = "test-user"
    w.created_at = datetime.now(UTC)
    w.updated_at = datetime.now(UTC)
    w.name = "My Bank"
    w.type = "bank_account"
    w.currency = "TWD"
    w.initial_balance = Decimal("10000")
    w.current_balance = Decimal("10000")
    w.credit_limit = None
    w.icon = None
    w.color = None
    w.sort_order = 0
    w.is_active = True
    w.is_private = False
    w.sync_provider = "manual"
    w.last_synced_at = None
    w.deleted_at = None
    return w


@pytest.fixture
def sample_transaction():
    """Create a sample Transaction instance for testing."""
    t = MagicMock(spec=Transaction)
    t.id = uuid7().hex
    t.space_id = "test-space"
    t.created_by = "test-user"
    t.created_at = datetime.now(UTC)
    t.updated_at = datetime.now(UTC)
    t.type = "expense"
    t.amount = Decimal("500")
    t.currency = "TWD"
    t.description = "Lunch"
    t.merchant = "Restaurant"
    t.payment_method = "cash"
    t.payment_detail = None
    t.category_id = None
    t.wallet_id = uuid7().hex
    t.transfer_to_wallet_id = None
    t.installment_plan_id = None
    t.installment_number = None
    t.paired_transaction_id = None
    t.status = "completed"
    t.settlement_amount = None
    t.original_currency = None
    t.exchange_rate = None
    t.fee = Decimal("0")
    t.invoice_number = None
    t.is_private = False
    t.transacted_at = datetime.now(UTC)
    t.deleted_at = None
    t.tags = []
    t.attachments = []
    return t


# ==================== Schema Validation Tests ====================


class TestSchemaValidation:
    """Test Pydantic schema creation, defaults, and validation."""

    def test_wallet_create_defaults(self):
        w = WalletCreate(name="Cash", type="cash")
        assert w.currency == "TWD"
        assert w.initial_balance == Decimal("0")
        assert w.is_private is False
        assert w.sort_order == 0

    def test_wallet_create_custom(self):
        w = WalletCreate(
            name="Savings",
            type="bank_account",
            currency="USD",
            initial_balance=Decimal("5000"),
            credit_limit=Decimal("10000"),
            is_private=True,
        )
        assert w.currency == "USD"
        assert w.initial_balance == Decimal("5000")
        assert w.credit_limit == Decimal("10000")
        assert w.is_private is True

    def test_wallet_update_partial(self):
        w = WalletUpdate(name="Updated")
        dump = w.model_dump(exclude_unset=True)
        assert dump == {"name": "Updated"}

    def test_transaction_create_required_fields(self):
        with pytest.raises(ValidationError):
            TransactionCreate()

    def test_transaction_create_with_tags(self):
        t = TransactionCreate(
            type="expense",
            amount=Decimal("100"),
            payment_method="cash",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
            tags=["food", "lunch"],
        )
        assert t.tags == ["food", "lunch"]
        assert t.fee == Decimal("0")
        assert t.status == "completed"

    def test_transaction_create_defaults(self):
        t = TransactionCreate(
            type="income",
            amount=Decimal("1000"),
            payment_method="bank_transfer",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
        )
        assert t.currency == "TWD"
        assert t.is_private is False
        assert t.tags == []

    def test_transfer_request(self):
        tr = TransferRequest(
            from_wallet_id="w1",
            to_wallet_id="w2",
            amount=Decimal("1000"),
            transacted_at=datetime.now(UTC),
        )
        assert tr.currency == "TWD"
        assert tr.fee == Decimal("0")
        assert tr.payment_method == "bank_transfer"

    def test_category_create_defaults(self):
        c = CategoryCreate(name="Food")
        assert c.parent_id is None
        assert c.sort_order == 0

    def test_subscription_create(self):
        s = SubscriptionCreate(
            name="Netflix",
            amount=Decimal("390"),
            billing_cycle="monthly",
            start_date=date(2026, 1, 1),
        )
        assert s.currency == "TWD"
        assert s.is_private is False

    def test_budget_create(self):
        b = BudgetCreate(
            year_month="2026-03",
            budget_amount=Decimal("50000"),
            savings_target=Decimal("10000"),
        )
        assert b.category_id is None

    def test_installment_plan_create(self):
        ip = InstallmentPlanCreate(
            description="MacBook Pro",
            total_amount=Decimal("60000"),
            num_installments=12,
            installment_amount=Decimal("5000"),
            wallet_id="w1",
            payment_method="credit_card",
            start_date=date(2026, 1, 1),
        )
        assert ip.fee_type == "none"
        assert ip.interest_rate == Decimal("0")

    def test_monthly_summary_response_defaults(self):
        s = MonthlySummaryResponse(year_month="2026-03")
        assert s.total_income == Decimal("0")
        assert s.net == Decimal("0")
        assert s.category_breakdown == []

    def test_category_breakdown_defaults(self):
        cb = CategoryBreakdown()
        assert cb.category_name == "未分類"
        assert cb.amount == Decimal("0")
        assert cb.pct == 0.0

    def test_reconcile_response(self):
        r = ReconcileResponse(
            wallet_id="w1",
            wallet_name="My Bank",
            current_balance=Decimal("10000"),
            calculated_balance=Decimal("9500"),
            difference=Decimal("500"),
            transaction_count=42,
        )
        assert r.last_synced_at is None


# ==================== Helper Function Tests ====================


class TestBalanceDelta:
    def test_income_positive(self):
        assert _balance_delta("income", Decimal("1000")) == Decimal("1000")

    def test_expense_negative(self):
        assert _balance_delta("expense", Decimal("500")) == Decimal("-500")

    def test_transfer_negative(self):
        assert _balance_delta("transfer", Decimal("300")) == Decimal("-300")


class TestPrivacyFilter:
    def test_with_user_id(self):
        mock_query = MagicMock()
        mock_query.where.return_value = mock_query
        apply_privacy_filter(mock_query, Wallet, "user-123")
        mock_query.where.assert_called_once()

    def test_without_user_id(self):
        mock_query = MagicMock()
        mock_query.where.return_value = mock_query
        apply_privacy_filter(mock_query, Wallet, None)
        mock_query.where.assert_called_once()


class TestNextBillingDate:
    def test_monthly(self):
        assert _next_billing_date(date(2026, 1, 15), "monthly") == date(2026, 2, 15)

    def test_monthly_end_of_month(self):
        assert _next_billing_date(date(2026, 1, 31), "monthly") == date(2026, 2, 28)

    def test_yearly(self):
        assert _next_billing_date(date(2026, 3, 1), "yearly") == date(2027, 3, 1)

    def test_weekly(self):
        assert _next_billing_date(date(2026, 3, 1), "weekly") == date(2026, 3, 8)

    def test_unknown_cycle_falls_back_to_monthly(self):
        assert _next_billing_date(date(2026, 3, 1), "biweekly") == date(2026, 4, 1)


# ==================== Service Layer Tests ====================


class TestWalletService:
    def test_before_create_sets_current_balance(self):
        data = WalletCreate(name="Cash", type="cash", initial_balance=Decimal("5000"))
        result = wallet_service.before_create(data)
        assert result["current_balance"] == Decimal("5000")

    def test_before_create_zero_balance(self):
        data = WalletCreate(name="New", type="bank_account")
        result = wallet_service.before_create(data)
        assert result["current_balance"] == Decimal("0")

    def test_to_response(self, sample_wallet):
        resp = wallet_service.to_response(sample_wallet)
        assert isinstance(resp, WalletResponse)
        assert resp.name == "My Bank"
        assert resp.current_balance == Decimal("10000")

    @pytest.mark.asyncio
    async def test_sync_creates_snapshot(self, mock_db, sample_wallet):
        mock_db.get.return_value = sample_wallet

        async def _fake_refresh(obj):
            now = datetime.now(UTC)
            for attr in ("created_at", "updated_at", "synced_at"):
                if hasattr(obj, attr) and getattr(obj, attr) is None:
                    setattr(obj, attr, now)

        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        data = WalletSyncRequest(synced_balance=Decimal("12000"), notes="Bank sync")

        with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
            result = await wallet_service.sync(
                mock_db, sample_wallet.id, data, "test-space", user_id="test-user"
            )

        assert result.synced_balance == Decimal("12000")
        assert sample_wallet.current_balance == Decimal("12000")
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_not_found(self, mock_db):
        mock_db.get.return_value = None
        data = WalletSyncRequest(synced_balance=Decimal("100"))
        with pytest.raises(NotFoundError):
            await wallet_service.sync(mock_db, "nonexistent", data, "space")

    @pytest.mark.asyncio
    async def test_reconcile(self, mock_db, sample_wallet):
        mock_db.get.return_value = sample_wallet
        income_r = MagicMock()
        income_r.scalar_one.return_value = Decimal("5000")
        expense_r = MagicMock()
        expense_r.scalar_one.return_value = Decimal("3000")
        transfer_r = MagicMock()
        transfer_r.scalar_one.return_value = Decimal("1000")
        fee_r = MagicMock()
        fee_r.scalar_one.return_value = Decimal("50")
        count_r = MagicMock()
        count_r.scalar_one.return_value = 10
        mock_db.execute = AsyncMock(side_effect=[income_r, expense_r, transfer_r, fee_r, count_r])

        with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
            result = await wallet_service.reconcile(mock_db, sample_wallet.id)

        # calculated = 10000 + 5000 - 3000 + 1000 - 50 = 12950
        assert result.calculated_balance == Decimal("12950")
        assert result.transaction_count == 10

    @pytest.mark.asyncio
    async def test_reconcile_not_found(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(NotFoundError):
            await wallet_service.reconcile(mock_db, "nonexistent")


class TestCategoryService:
    def test_to_response_with_children(self):
        child = MagicMock(spec=Category)
        child.id = "c2"
        child.space_id = "sp"
        child.created_by = "u"
        child.created_at = datetime.now(UTC)
        child.updated_at = datetime.now(UTC)
        child.name = "Lunch"
        child.parent_id = "c1"
        child.icon = None
        child.color = None
        child.sort_order = 0
        child.is_active = True
        child.is_private = False
        child.children = []

        parent = MagicMock(spec=Category)
        parent.id = "c1"
        parent.space_id = "sp"
        parent.created_by = "u"
        parent.created_at = datetime.now(UTC)
        parent.updated_at = datetime.now(UTC)
        parent.name = "Food"
        parent.parent_id = None
        parent.icon = None
        parent.color = None
        parent.sort_order = 0
        parent.is_active = True
        parent.is_private = False
        parent.children = [child]

        resp = category_service.to_response(parent)
        assert isinstance(resp, CategoryResponse)
        assert len(resp.children) == 1
        assert resp.children[0].name == "Lunch"

    def test_to_response_filters_inactive_children(self):
        inactive_child = MagicMock(spec=Category)
        inactive_child.is_active = False

        parent = MagicMock(spec=Category)
        parent.id = "c1"
        parent.space_id = "sp"
        parent.created_by = "u"
        parent.created_at = datetime.now(UTC)
        parent.updated_at = datetime.now(UTC)
        parent.name = "Food"
        parent.parent_id = None
        parent.icon = None
        parent.color = None
        parent.sort_order = 0
        parent.is_active = True
        parent.is_private = False
        parent.children = [inactive_child]

        resp = category_service.to_response(parent)
        assert len(resp.children) == 0


class TestTransactionService:
    def test_before_create_excludes_tags(self):
        data = TransactionCreate(
            type="expense",
            amount=Decimal("100"),
            payment_method="cash",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
            tags=["food"],
        )
        result = transaction_service.before_create(data)
        assert "tags" not in result

    def test_to_response_with_tags(self, sample_transaction):
        tag1 = MagicMock()
        tag1.tag = "food"
        tag2 = MagicMock()
        tag2.tag = "lunch"
        sample_transaction.tags = [tag1, tag2]
        resp = transaction_service.to_response(sample_transaction)
        assert resp.tags == ["food", "lunch"]

    def test_to_response_empty_tags(self, sample_transaction):
        sample_transaction.tags = []
        resp = transaction_service.to_response(sample_transaction)
        assert resp.tags == []

    @pytest.mark.asyncio
    async def test_create_completed_adjusts_balance(self, mock_db):
        data = TransactionCreate(
            type="expense",
            amount=Decimal("500"),
            payment_method="cash",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
            tags=["food"],
        )
        instance = MagicMock(spec=Transaction)
        instance.id = uuid7().hex
        instance.status = "completed"
        instance.type = "expense"
        instance.amount = Decimal("500")
        instance.wallet_id = "w1"
        instance.fee = Decimal("0")

        with patch.object(
            TransactionService.__bases__[0], "create", new_callable=AsyncMock, return_value=instance
        ):
            with patch(
                "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
            ) as mock_adjust:
                with patch(
                    "src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())
                ):
                    await transaction_service.create(mock_db, "space", data, user_id="user")
                    mock_adjust.assert_called_once_with(mock_db, "w1", Decimal("-500"))

    @pytest.mark.asyncio
    async def test_create_scheduled_no_balance_change(self, mock_db):
        data = TransactionCreate(
            type="expense",
            amount=Decimal("500"),
            payment_method="cash",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
            status="scheduled",
        )
        instance = MagicMock(spec=Transaction)
        instance.id = uuid7().hex
        instance.status = "scheduled"
        instance.type = "expense"
        instance.amount = Decimal("500")
        instance.wallet_id = "w1"
        instance.fee = Decimal("0")

        with patch.object(
            TransactionService.__bases__[0], "create", new_callable=AsyncMock, return_value=instance
        ):
            with patch(
                "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
            ) as mock_adjust:
                with patch(
                    "src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())
                ):
                    await transaction_service.create(mock_db, "space", data)
                    mock_adjust.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_with_fee_deducts_fee(self, mock_db):
        data = TransactionCreate(
            type="expense",
            amount=Decimal("500"),
            payment_method="card",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
            fee=Decimal("10"),
        )
        instance = MagicMock(spec=Transaction)
        instance.id = uuid7().hex
        instance.status = "completed"
        instance.type = "expense"
        instance.amount = Decimal("500")
        instance.wallet_id = "w1"
        instance.fee = Decimal("10")

        with patch.object(
            TransactionService.__bases__[0], "create", new_callable=AsyncMock, return_value=instance
        ):
            with patch(
                "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
            ) as mock_adjust:
                with patch(
                    "src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())
                ):
                    await transaction_service.create(mock_db, "space", data)
                    assert mock_adjust.call_count == 2
                    calls = mock_adjust.call_args_list
                    assert calls[0].args == (mock_db, "w1", Decimal("-500"))
                    assert calls[1].args == (mock_db, "w1", Decimal("-10"))

    @pytest.mark.asyncio
    async def test_delete_reverses_completed_balance(self, mock_db, sample_transaction):
        sample_transaction.status = "completed"
        sample_transaction.type = "expense"
        sample_transaction.amount = Decimal("500")
        sample_transaction.fee = Decimal("10")
        mock_db.get = AsyncMock(return_value=sample_transaction)

        with patch(
            "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
                result = await transaction_service.delete(mock_db, sample_transaction.id)

        assert result is True
        assert mock_adjust.call_count == 2
        # Reverse expense delta: -(-500) = +500, restore fee: +10
        assert mock_adjust.call_args_list[0].args[2] == Decimal("500")
        assert mock_adjust.call_args_list[1].args[2] == Decimal("10")

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
            result = await transaction_service.delete(mock_db, "nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_scheduled_no_balance_reversal(self, mock_db, sample_transaction):
        sample_transaction.status = "scheduled"
        mock_db.get = AsyncMock(return_value=sample_transaction)

        with patch(
            "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
                result = await transaction_service.delete(mock_db, sample_transaction.id)

        assert result is True
        mock_adjust.assert_not_called()


class TestTransferService:
    @pytest.mark.asyncio
    async def test_same_wallet_raises(self, mock_db):
        with pytest.raises(BadRequestError, match="same wallet"):
            await transfer_service.transfer(mock_db, "space", "w1", "w1", Decimal("100"))

    @pytest.mark.asyncio
    async def test_negative_amount_raises(self, mock_db):
        with pytest.raises(BadRequestError, match="positive"):
            await transfer_service.transfer(mock_db, "space", "w1", "w2", Decimal("-100"))

    @pytest.mark.asyncio
    async def test_zero_amount_raises(self, mock_db):
        with pytest.raises(BadRequestError, match="positive"):
            await transfer_service.transfer(mock_db, "space", "w1", "w2", Decimal("0"))

    @pytest.mark.asyncio
    async def test_wallet_not_found_raises(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await transfer_service.transfer(mock_db, "space", "w1", "w2", Decimal("100"))

    @pytest.mark.asyncio
    async def test_transfer_creates_paired_transactions(self, mock_db):
        w1 = MagicMock(spec=Wallet, id="aaa")
        w2 = MagicMock(spec=Wallet, id="bbb")
        mock_db.get = AsyncMock(side_effect=lambda model, wid, **kw: w1 if wid == "aaa" else w2)

        with patch("src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock):
            with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
                out_txn, in_txn = await transfer_service.transfer(
                    mock_db, "space", "aaa", "bbb", Decimal("1000"), fee=Decimal("50")
                )

        assert mock_db.add.call_count == 2
        assert out_txn.paired_transaction_id == in_txn.id
        assert in_txn.paired_transaction_id == out_txn.id
        assert out_txn.type == "transfer"
        assert out_txn.fee == Decimal("50")
        assert in_txn.fee == Decimal("0")

    @pytest.mark.asyncio
    async def test_transfer_sorted_lock_order(self, mock_db):
        lock_order = []

        async def mock_get(model, wid, **kwargs):
            lock_order.append(wid)
            return MagicMock(spec=Wallet, id=wid)

        mock_db.get = mock_get

        with patch("src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock):
            with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
                await transfer_service.transfer(mock_db, "space", "zzz", "aaa", Decimal("100"))

        assert lock_order == ["aaa", "zzz"]

    @pytest.mark.asyncio
    async def test_transfer_balance_adjustments(self, mock_db):
        w1 = MagicMock(spec=Wallet, id="aaa")
        w2 = MagicMock(spec=Wallet, id="bbb")
        mock_db.get = AsyncMock(side_effect=lambda model, wid, **kw: w1 if wid == "aaa" else w2)

        with patch(
            "src.modules.finance.services._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())):
                await transfer_service.transfer(
                    mock_db, "space", "aaa", "bbb", Decimal("1000"), fee=Decimal("50")
                )

        assert mock_adjust.call_count == 2
        # from_wallet: -(1000 + 50) = -1050
        assert mock_adjust.call_args_list[0].args == (mock_db, "aaa", Decimal("-1050"))
        # to_wallet: +1000
        assert mock_adjust.call_args_list[1].args == (mock_db, "bbb", Decimal("1000"))


class TestBudgetService:
    @pytest.mark.asyncio
    async def test_upsert_creates_new(self, mock_db):
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=execute_result)

        data = BudgetCreate(year_month="2026-03", budget_amount=Decimal("50000"))

        with patch.object(
            BudgetService.__bases__[0], "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock(spec=Budget)
            await budget_service.upsert(mock_db, "space", data, user_id="user")
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, mock_db):
        existing = MagicMock(spec=Budget)
        existing.budget_amount = Decimal("40000")
        existing.savings_target = Decimal("5000")

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=execute_result)

        data = BudgetCreate(
            year_month="2026-03",
            budget_amount=Decimal("60000"),
            savings_target=Decimal("15000"),
        )

        await budget_service.upsert(mock_db, "space", data)
        assert existing.budget_amount == Decimal("60000")
        assert existing.savings_target == Decimal("15000")

    @pytest.mark.asyncio
    async def test_get_status_exceeded(self, mock_db):
        budget = MagicMock(spec=Budget)
        budget.id = "b1"
        budget.category_id = "cat1"
        budget.year_month = "2026-03"
        budget.budget_amount = Decimal("10000")
        budget.is_private = False

        budget_result = MagicMock()
        budget_result.scalars.return_value.all.return_value = [budget]

        spending_row = MagicMock()
        spending_row.category_id = "cat1"
        spending_row.total = Decimal("15000")
        spending_result = MagicMock()
        spending_result.all.return_value = [spending_row]

        mock_db.execute = AsyncMock(side_effect=[budget_result, spending_result])

        with patch(
            "src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())
        ) as mock_bus:
            result = await budget_service.get_status(mock_db, "space", "2026-03")

        assert result["budgets"][0]["exceeded"] is True
        assert result["budgets"][0]["remaining"] == Decimal("-5000")
        mock_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_status_under_budget(self, mock_db):
        budget = MagicMock(spec=Budget)
        budget.id = "b1"
        budget.category_id = "cat1"
        budget.year_month = "2026-03"
        budget.budget_amount = Decimal("50000")
        budget.is_private = False

        budget_result = MagicMock()
        budget_result.scalars.return_value.all.return_value = [budget]

        spending_row = MagicMock()
        spending_row.category_id = "cat1"
        spending_row.total = Decimal("20000")
        spending_result = MagicMock()
        spending_result.all.return_value = [spending_row]

        mock_db.execute = AsyncMock(side_effect=[budget_result, spending_result])

        with patch(
            "src.modules.finance.services.event_bus", MagicMock(publish=AsyncMock())
        ) as mock_bus:
            result = await budget_service.get_status(mock_db, "space", "2026-03")

        assert result["budgets"][0]["exceeded"] is False
        assert result["budgets"][0]["remaining"] == Decimal("30000")
        mock_bus.publish.assert_not_called()


class TestSummaryService:
    @pytest.mark.asyncio
    async def test_monthly_summary(self, mock_db):
        income_row = MagicMock(type="income", total=Decimal("100000"), cnt=5)
        expense_row = MagicMock(type="expense", total=Decimal("60000"), cnt=15)
        totals_result = MagicMock()
        totals_result.all.return_value = [income_row, expense_row]

        cat_row = MagicMock(
            category_id="cat1",
            category_name="Food",
            category_icon=None,
            total=Decimal("30000"),
            cnt=10,
        )
        cat_result = MagicMock()
        cat_result.all.return_value = [cat_row]

        wallet_result = MagicMock()
        wallet_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[totals_result, cat_result, wallet_result])

        result = await summary_service.monthly_summary(mock_db, "space", "2026-03")
        assert result.total_income == Decimal("100000")
        assert result.total_expense == Decimal("60000")
        assert result.net == Decimal("40000")
        assert result.transaction_count == 20
        assert len(result.category_breakdown) == 1
        assert result.category_breakdown[0].pct == 50.0

    @pytest.mark.asyncio
    async def test_monthly_summary_empty(self, mock_db):
        totals_result = MagicMock()
        totals_result.all.return_value = []
        cat_result = MagicMock()
        cat_result.all.return_value = []
        wallet_result = MagicMock()
        wallet_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[totals_result, cat_result, wallet_result])

        result = await summary_service.monthly_summary(mock_db, "space", "2026-03")
        assert result.total_income == Decimal("0")
        assert result.total_expense == Decimal("0")
        assert result.net == Decimal("0")
        assert result.transaction_count == 0


# ==================== Cron Job Tests ====================


class TestProcessInstallmentDue:
    @pytest.mark.asyncio
    async def test_no_due_returns_zero(self, mock_db):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await process_installment_due(mock_db)
        assert result == 0

    @pytest.mark.asyncio
    async def test_processes_due_transaction(self, mock_db):
        txn = MagicMock(spec=Transaction)
        txn.id = "txn1"
        txn.status = "scheduled"
        txn.amount = Decimal("5000")
        txn.wallet_id = "w1"
        txn.fee = Decimal("0")
        txn.installment_plan_id = "plan1"
        txn.installment_number = 1
        txn.created_by = "user1"

        due_result = MagicMock()
        due_result.scalars.return_value.all.return_value = [txn]

        plan = MagicMock(spec=InstallmentPlan)
        plan.status = "active"
        plan.description = "MacBook"
        plan.total_amount = Decimal("60000")
        plan.num_installments = 12
        plan.created_by = "user1"

        remaining_result = MagicMock()
        remaining_result.scalar_one.return_value = 5

        mock_db.execute = AsyncMock(side_effect=[due_result, remaining_result])
        mock_db.get = AsyncMock(return_value=plan)

        with patch(
            "src.modules.finance.cron._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.cron.event_bus") as mock_bus:
                mock_bus.publish = AsyncMock()
                result = await process_installment_due(mock_db)

        assert result == 1
        assert txn.status == "completed"
        mock_adjust.assert_called_once_with(mock_db, "w1", Decimal("-5000"))

    @pytest.mark.asyncio
    async def test_processes_due_with_fee(self, mock_db):
        txn = MagicMock(spec=Transaction)
        txn.id = "txn1"
        txn.status = "scheduled"
        txn.amount = Decimal("5000")
        txn.wallet_id = "w1"
        txn.fee = Decimal("100")
        txn.installment_plan_id = "plan1"
        txn.installment_number = 1
        txn.created_by = "user1"

        due_result = MagicMock()
        due_result.scalars.return_value.all.return_value = [txn]

        plan = MagicMock(spec=InstallmentPlan)
        plan.status = "active"

        remaining_result = MagicMock()
        remaining_result.scalar_one.return_value = 5

        mock_db.execute = AsyncMock(side_effect=[due_result, remaining_result])
        mock_db.get = AsyncMock(return_value=plan)

        with patch(
            "src.modules.finance.cron._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.cron.event_bus") as mock_bus:
                mock_bus.publish = AsyncMock()
                await process_installment_due(mock_db)

        assert mock_adjust.call_count == 2
        assert mock_adjust.call_args_list[0].args == (mock_db, "w1", Decimal("-5000"))
        assert mock_adjust.call_args_list[1].args == (mock_db, "w1", Decimal("-100"))

    @pytest.mark.asyncio
    async def test_completes_plan_when_all_done(self, mock_db):
        txn = MagicMock(spec=Transaction)
        txn.id = "txn1"
        txn.status = "scheduled"
        txn.amount = Decimal("5000")
        txn.wallet_id = "w1"
        txn.fee = Decimal("0")
        txn.installment_plan_id = "plan1"
        txn.installment_number = 12
        txn.created_by = "user1"

        due_result = MagicMock()
        due_result.scalars.return_value.all.return_value = [txn]

        plan = MagicMock(spec=InstallmentPlan)
        plan.status = "active"
        plan.description = "MacBook"
        plan.total_amount = Decimal("60000")
        plan.num_installments = 12
        plan.created_by = "user1"

        remaining_result = MagicMock()
        remaining_result.scalar_one.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[due_result, remaining_result])
        mock_db.get = AsyncMock(return_value=plan)

        with patch("src.modules.finance.cron._adjust_wallet_balance", new_callable=AsyncMock):
            with patch("src.modules.finance.cron.event_bus") as mock_bus:
                mock_bus.publish = AsyncMock()
                await process_installment_due(mock_db)

        assert plan.status == "completed"

    @pytest.mark.asyncio
    async def test_idempotent_skips_completed(self, mock_db):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await process_installment_due(mock_db)
        assert result == 0


class TestProcessSubscriptionBilling:
    @pytest.mark.asyncio
    async def test_no_due_returns_zero(self, mock_db):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await process_subscription_billing(mock_db, "space")
        assert result == 0

    @pytest.mark.asyncio
    async def test_bills_due_subscription(self, mock_db):
        sub = MagicMock(spec=Subscription)
        sub.id = "sub1"
        sub.name = "Netflix"
        sub.amount = Decimal("390")
        sub.currency = "TWD"
        sub.billing_cycle = "monthly"
        sub.payment_method = "credit_card"
        sub.payment_detail = None
        sub.category_id = "cat1"
        sub.wallet_id = "w1"
        sub.next_billing = date(2026, 3, 1)
        sub.created_by = "user1"

        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub]

        dedup_result = MagicMock()
        dedup_result.scalar_one.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[subs_result, dedup_result])

        with patch(
            "src.modules.finance.cron._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.cron.event_bus") as mock_bus:
                mock_bus.publish = AsyncMock()
                result = await process_subscription_billing(mock_db, "space")

        assert result == 1
        mock_db.add.assert_called_once()
        txn = mock_db.add.call_args[0][0]
        assert txn.type == "expense"
        assert txn.amount == Decimal("390")
        assert txn.invoice_number == "sub:sub1:2026-03-01"
        mock_adjust.assert_called_once_with(mock_db, "w1", Decimal("-390"))
        assert sub.next_billing == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_idempotent_skips_already_billed(self, mock_db):
        sub = MagicMock(spec=Subscription)
        sub.id = "sub1"
        sub.name = "Netflix"
        sub.billing_cycle = "monthly"
        sub.next_billing = date(2026, 3, 1)

        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub]

        dedup_result = MagicMock()
        dedup_result.scalar_one.return_value = 1

        mock_db.execute = AsyncMock(side_effect=[subs_result, dedup_result])

        with patch("src.modules.finance.cron.event_bus"):
            result = await process_subscription_billing(mock_db, "space")

        assert result == 0
        # next_billing should still advance
        assert sub.next_billing == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_no_wallet_skips_balance(self, mock_db):
        sub = MagicMock(spec=Subscription)
        sub.id = "sub2"
        sub.name = "GitHub"
        sub.amount = Decimal("150")
        sub.currency = "TWD"
        sub.billing_cycle = "monthly"
        sub.payment_method = None
        sub.payment_detail = None
        sub.category_id = None
        sub.wallet_id = None
        sub.next_billing = date(2026, 3, 1)
        sub.created_by = "user1"

        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub]

        dedup_result = MagicMock()
        dedup_result.scalar_one.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[subs_result, dedup_result])

        with patch(
            "src.modules.finance.cron._adjust_wallet_balance", new_callable=AsyncMock
        ) as mock_adjust:
            with patch("src.modules.finance.cron.event_bus") as mock_bus:
                mock_bus.publish = AsyncMock()
                result = await process_subscription_billing(mock_db, "space")

        assert result == 1
        mock_adjust.assert_not_called()


class TestRunAllCron:
    @pytest.mark.asyncio
    async def test_runs_both_jobs(self, mock_db):
        with patch(
            "src.modules.finance.cron.process_installment_due",
            new_callable=AsyncMock,
            return_value=3,
        ):
            with patch(
                "src.modules.finance.cron.process_subscription_billing",
                new_callable=AsyncMock,
                return_value=2,
            ):
                result = await run_all_cron(mock_db, "space")

        assert result["installments_processed"] == 3
        assert result["subscriptions_processed"] == 2
        assert result["total_processed"] == 5


# ==================== Route Layer Tests ====================


class TestRoutes:
    @pytest.fixture
    def test_app(self):
        from fastapi import FastAPI
        from src.modules.finance.routes import router

        app = FastAPI()
        app.include_router(router, prefix="/api/finance")
        return app

    @pytest.fixture
    def mock_user(self):
        return {"user_id": "test-user", "role": "admin", "space_id": "default"}

    @pytest.fixture
    def route_db(self):
        return AsyncMock()

    @pytest_asyncio.fixture
    async def client(self, test_app, mock_user, route_db, monkeypatch):
        from httpx import ASGITransport, AsyncClient
        from src.shared.deps import get_db

        monkeypatch.setattr(
            "src.shared.deps.get_current_user",
            lambda request: mock_user,
        )

        async def override_db():
            yield route_db

        test_app.dependency_overrides[get_db] = override_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        test_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_wallets(self, client, route_db):
        with patch("src.modules.finance.routes.wallet_service") as mock_svc:
            mock_svc.list = AsyncMock(
                return_value=PaginatedResponse(items=[], total=0, page=1, page_size=20)
            )
            resp = await client.get("/api/finance/wallets")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_create_wallet(self, client, route_db):
        wallet_resp = WalletResponse(
            id="w1",
            space_id="default",
            created_by="test-user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            name="Cash",
            type="cash",
            currency="TWD",
            initial_balance=Decimal("0"),
            current_balance=Decimal("0"),
        )
        with patch("src.modules.finance.routes.wallet_service") as mock_svc:
            mock_svc.create = AsyncMock(return_value=MagicMock())
            mock_svc.to_response.return_value = wallet_resp
            route_db.commit = AsyncMock()
            resp = await client.post(
                "/api/finance/wallets",
                json={"name": "Cash", "type": "cash"},
            )

        assert resp.status_code == 201
        assert resp.json()["name"] == "Cash"

    @pytest.mark.asyncio
    async def test_create_transaction(self, client, route_db):
        txn_resp = TransactionResponse(
            id="t1",
            space_id="default",
            created_by="test-user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            type="expense",
            amount=Decimal("500"),
            currency="TWD",
            payment_method="cash",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
        )
        with patch("src.modules.finance.routes.transaction_service") as mock_svc:
            mock_svc.create = AsyncMock(return_value=MagicMock())
            mock_svc.to_response.return_value = txn_resp
            route_db.commit = AsyncMock()
            resp = await client.post(
                "/api/finance/transactions",
                json={
                    "type": "expense",
                    "amount": "500",
                    "payment_method": "cash",
                    "wallet_id": "w1",
                    "transacted_at": datetime.now(UTC).isoformat(),
                },
            )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_execute_transfer(self, client, route_db):
        out_resp = TransactionResponse(
            id="t1",
            space_id="default",
            created_by="user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            type="transfer",
            amount=Decimal("1000"),
            currency="TWD",
            payment_method="bank_transfer",
            wallet_id="w1",
            transacted_at=datetime.now(UTC),
        )
        in_resp = TransactionResponse(
            id="t2",
            space_id="default",
            created_by="user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            type="transfer",
            amount=Decimal("1000"),
            currency="TWD",
            payment_method="bank_transfer",
            wallet_id="w2",
            transacted_at=datetime.now(UTC),
        )
        with patch("src.modules.finance.routes.transfer_service") as mock_transfer:
            with patch("src.modules.finance.routes.transaction_service") as mock_txn_svc:
                mock_transfer.transfer = AsyncMock(return_value=(MagicMock(), MagicMock()))
                mock_txn_svc.to_response.side_effect = [out_resp, in_resp]
                route_db.commit = AsyncMock()
                resp = await client.post(
                    "/api/finance/transfer",
                    json={
                        "from_wallet_id": "w1",
                        "to_wallet_id": "w2",
                        "amount": "1000",
                        "transacted_at": datetime.now(UTC).isoformat(),
                    },
                )

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_get_monthly_summary(self, client, route_db):
        summary = MonthlySummaryResponse(
            year_month="2026-03",
            total_income=Decimal("100000"),
            total_expense=Decimal("60000"),
            net=Decimal("40000"),
            transaction_count=20,
        )
        with patch("src.modules.finance.routes.summary_service") as mock_svc:
            mock_svc.monthly_summary = AsyncMock(return_value=summary)
            resp = await client.get("/api/finance/summary/2026-03")

        assert resp.status_code == 200
        data = resp.json()
        assert data["year_month"] == "2026-03"
        assert data["net"] == "40000"

    @pytest.mark.asyncio
    async def test_upsert_budget(self, client, route_db):
        budget_resp = BudgetResponse(
            id="b1",
            space_id="default",
            created_by="test-user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            year_month="2026-03",
            budget_amount=Decimal("50000"),
        )
        with patch("src.modules.finance.routes.budget_service") as mock_svc:
            mock_svc.upsert = AsyncMock(return_value=MagicMock())
            mock_svc.to_response.return_value = budget_resp
            route_db.commit = AsyncMock()
            resp = await client.post(
                "/api/finance/budgets",
                json={"year_month": "2026-03", "budget_amount": "50000"},
            )

        assert resp.status_code == 201
        assert resp.json()["year_month"] == "2026-03"

    @pytest.mark.asyncio
    async def test_list_wallets_pagination(self, client, route_db):
        with patch("src.modules.finance.routes.wallet_service") as mock_svc:
            mock_svc.list = AsyncMock(
                return_value=PaginatedResponse(items=[], total=50, page=2, page_size=10)
            )
            resp = await client.get("/api/finance/wallets?page=2&page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 50
        assert data["page"] == 2
        assert data["page_size"] == 10
