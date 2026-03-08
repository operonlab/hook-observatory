"""Finance services — CRUD + balance management + reconciliation.

This is the PUBLIC API of the finance module.
Other modules import from here, never from models.py.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import FinanceEvents
from src.modules.finance.lifecycle import TransactionLifecycle
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.fsm import emit_state_changed, validate_transition
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import (
    Budget,
    Category,
    InstallmentPlan,
    Subscription,
    Transaction,
    TransactionTag,
    Wallet,
    WalletSnapshot,
)
from .schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
    CategoryBreakdown,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    InstallmentPlanCreate,
    InstallmentPlanResponse,
    InstallmentPlanUpdate,
    MonthlySummaryResponse,
    MonthlyTrendResponse,
    NetWorthPointResponse,
    ReconcileResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
    WalletCreate,
    WalletOverviewItem,
    WalletResponse,
    WalletSnapshotResponse,
    WalletSyncRequest,
    WalletUpdate,
)

# ======================== Privacy Filter ========================


def apply_privacy_filter(query, model, user_id: str | None):
    """Filter out private records unless owned by current user."""
    if user_id:
        return query.where(or_(model.is_private == False, model.created_by == user_id))  # noqa: E712
    return query.where(model.is_private == False)  # noqa: E712


def _soft_delete_filter(query, model):
    """Exclude soft-deleted records."""
    if hasattr(model, "deleted_at"):
        return query.where(model.deleted_at == None)  # noqa: E711
    return query


# ======================== Balance Helpers ========================


def _balance_delta(txn_type: str, amount: Decimal) -> Decimal:
    """Compute the delta to apply to wallet.current_balance.

    income  → +amount
    expense → -amount
    transfer (source wallet) → -amount
    """
    if txn_type == "income":
        return amount
    return -amount


async def _adjust_wallet_balance(db: AsyncSession, wallet_id: str, delta: Decimal) -> None:
    """Atomic delta update on wallet current_balance."""
    await db.execute(
        update(Wallet)
        .where(Wallet.id == wallet_id)
        .values(current_balance=Wallet.current_balance + delta)
    )


# ======================== Wallet Service ========================


class WalletService(BaseCRUDService[Wallet, WalletCreate, WalletUpdate, WalletResponse]):
    model = Wallet
    audit_module = "finance"
    audit_entity_type = "wallets"

    def before_create(self, data: WalletCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        d["current_balance"] = d["initial_balance"]
        return d

    def to_response(self, instance: Wallet) -> WalletResponse:
        return WalletResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            type=instance.type,
            currency=instance.currency,
            initial_balance=instance.initial_balance,
            current_balance=instance.current_balance,
            credit_limit=instance.credit_limit,
            icon=instance.icon,
            color=instance.color,
            sort_order=instance.sort_order,
            is_active=instance.is_active,
            is_private=instance.is_private,
            sync_provider=instance.sync_provider,
            last_synced_at=instance.last_synced_at,
            deleted_at=instance.deleted_at,
        )

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
        include_inactive: bool = False,
    ) -> PaginatedResponse[WalletResponse]:
        p = pagination or PaginationParams()
        base = select(Wallet).where(Wallet.space_id == space_id)
        base = _soft_delete_filter(base, Wallet)
        base = apply_privacy_filter(base, Wallet, user_id)
        if not include_inactive:
            base = base.where(Wallet.is_active == True)  # noqa: E712
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(Wallet.sort_order, Wallet.name)
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[Wallet] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[WalletResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    # --- Phase C: Sync & Reconciliation ---

    async def sync(
        self,
        db: AsyncSession,
        wallet_id: str,
        data: WalletSyncRequest,
        space_id: str,
        user_id: str | None = None,
    ) -> WalletSnapshotResponse:
        """Record synced balance and update wallet.current_balance."""
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise NotFoundError("Wallet not found", code="finance.wallet_not_found")

        calculated = wallet.current_balance
        snapshot = WalletSnapshot(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            wallet_id=wallet_id,
            synced_balance=data.synced_balance,
            calculated_balance=calculated,
            snapshot_type="reconciliation",
            notes=data.notes,
        )
        db.add(snapshot)

        wallet.current_balance = data.synced_balance
        wallet.last_synced_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(snapshot)

        await event_bus.publish(
            Event(
                type=FinanceEvents.WALLET_SYNCED,
                data={"wallet_id": wallet_id, "synced_balance": str(data.synced_balance)},
                source="finance",
                user_id=user_id,
            )
        )

        return WalletSnapshotResponse(
            id=snapshot.id,
            space_id=snapshot.space_id,
            created_by=snapshot.created_by,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            wallet_id=snapshot.wallet_id,
            synced_balance=snapshot.synced_balance,
            calculated_balance=snapshot.calculated_balance,
            difference=snapshot.synced_balance - snapshot.calculated_balance,
            snapshot_type=snapshot.snapshot_type,
            notes=snapshot.notes,
            synced_at=snapshot.synced_at,
        )

    async def reconcile(
        self,
        db: AsyncSession,
        wallet_id: str,
        user_id: str | None = None,
    ) -> ReconcileResponse:
        """Return reconciliation summary: current vs calculated balance."""
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise NotFoundError("Wallet not found", code="finance.wallet_not_found")

        # Calculate balance from initial + sum of all completed transactions
        # Only count non-deleted transactions
        txn_filter = [
            Transaction.wallet_id == wallet_id,
            Transaction.status == "completed",
        ]
        txn_filter.append(Transaction.deleted_at == None)  # noqa: E711

        income_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    *txn_filter,
                    Transaction.type == "income",
                )
            )
        ).scalar_one()

        expense_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    *txn_filter,
                    Transaction.type.in_(["expense", "transfer"]),
                )
            )
        ).scalar_one()

        # Transfers into this wallet
        transfer_in = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.transfer_to_wallet_id == wallet_id,
                    Transaction.type == "transfer",
                    Transaction.status == "completed",
                    Transaction.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        fee_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.fee), 0)).where(
                    *txn_filter,
                )
            )
        ).scalar_one()

        calculated = wallet.initial_balance + income_sum - expense_sum + transfer_in - fee_sum

        txn_count = (await db.execute(select(func.count()).where(*txn_filter))).scalar_one()

        await event_bus.publish(
            Event(
                type=FinanceEvents.WALLET_RECONCILED,
                data={
                    "wallet_id": wallet_id,
                    "current_balance": str(wallet.current_balance),
                    "calculated_balance": str(calculated),
                },
                source="finance",
                user_id=user_id,
            )
        )

        return ReconcileResponse(
            wallet_id=wallet.id,
            wallet_name=wallet.name,
            current_balance=wallet.current_balance,
            calculated_balance=calculated,
            difference=wallet.current_balance - calculated,
            transaction_count=txn_count,
            last_synced_at=wallet.last_synced_at,
        )


# ======================== Category Service ========================


class CategoryService(BaseCRUDService[Category, CategoryCreate, CategoryUpdate, CategoryResponse]):
    model = Category
    audit_module = "finance"
    audit_entity_type = "categories"

    def to_response(self, instance: Category) -> CategoryResponse:
        children = []
        # Check __dict__ to avoid triggering async-incompatible lazy load
        if "children" in instance.__dict__ and instance.children:
            children = [self.to_response(c) for c in instance.children if c.is_active]
        return CategoryResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            parent_id=instance.parent_id,
            icon=instance.icon,
            color=instance.color,
            sort_order=instance.sort_order,
            is_active=instance.is_active,
            is_private=instance.is_private,
            children=children,
        )

    async def list_tree(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> list[CategoryResponse]:
        """Return top-level categories with children loaded (selectin)."""
        q = select(Category).where(
            Category.space_id == space_id,
            Category.parent_id == None,  # noqa: E711
            Category.is_active == True,  # noqa: E712
            Category.deleted_at == None,  # noqa: E711
        )
        q = apply_privacy_filter(q, Category, user_id)
        q = q.order_by(Category.sort_order, Category.name)
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
    ) -> PaginatedResponse[CategoryResponse]:
        p = pagination or PaginationParams()
        base = select(Category).where(
            Category.space_id == space_id,
            Category.is_active == True,  # noqa: E712
            Category.deleted_at == None,  # noqa: E711
        )
        base = apply_privacy_filter(base, Category, user_id)
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(Category.sort_order, Category.name)
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[CategoryResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Transaction Service ========================


class TransactionService(
    BaseCRUDService[Transaction, TransactionCreate, TransactionUpdate, TransactionResponse]
):
    model = Transaction
    audit_module = "finance"
    audit_entity_type = "transactions"

    def before_create(self, data: TransactionCreate, **kwargs: Any) -> dict:
        d = data.model_dump(exclude={"tags"})
        return d

    def to_response(self, instance: Transaction) -> TransactionResponse:
        tags = []
        # Check __dict__ to avoid triggering async-incompatible lazy load
        if "tags" in instance.__dict__ and instance.tags:
            tags = [t.tag for t in instance.tags]
        return TransactionResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            icon_url=instance.icon_url,
            type=instance.type,
            amount=instance.amount,
            currency=instance.currency,
            description=instance.description,
            merchant=instance.merchant,
            payment_method=instance.payment_method,
            payment_detail=instance.payment_detail,
            category_id=instance.category_id,
            wallet_id=instance.wallet_id,
            transfer_to_wallet_id=instance.transfer_to_wallet_id,
            installment_plan_id=instance.installment_plan_id,
            installment_number=instance.installment_number,
            paired_transaction_id=instance.paired_transaction_id,
            status=instance.status,
            settlement_amount=instance.settlement_amount,
            original_currency=instance.original_currency,
            exchange_rate=instance.exchange_rate,
            fee=instance.fee,
            invoice_number=instance.invoice_number,
            is_private=instance.is_private,
            transacted_at=instance.transacted_at,
            tags=tags,
        )

    async def create(
        self, db: AsyncSession, space_id: str, data: TransactionCreate, user_id: str | None = None
    ) -> Transaction:
        instance = await super().create(db, space_id, data, user_id)

        # Create tags
        for tag_name in data.tags:
            db.add(TransactionTag(transaction_id=instance.id, tag=tag_name))

        # Balance delta (only for completed transactions)
        if instance.status == "completed":
            delta = _balance_delta(instance.type, instance.amount)
            await _adjust_wallet_balance(db, instance.wallet_id, delta)
            if instance.fee:
                await _adjust_wallet_balance(db, instance.wallet_id, -instance.fee)

        await db.flush()

        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSACTION_CREATED,
                data={
                    "transaction_id": instance.id,
                    "type": instance.type,
                    "amount": str(instance.amount),
                },
                source="finance",
                user_id=user_id,
            )
        )
        return instance

    async def update(
        self, db: AsyncSession, entity_id: str, data: TransactionUpdate, user_id: str | None = None
    ) -> Transaction | None:
        instance = await self.get(db, entity_id)
        if not instance:
            return None

        old_snapshot = self._snapshot(instance)
        old_amount = instance.amount
        old_type = instance.type
        old_wallet_id = instance.wallet_id
        old_status = instance.status
        old_fee = instance.fee or Decimal("0")

        # Update scalar fields
        update_data = data.model_dump(exclude_unset=True, exclude={"tags"})

        # FSM guard: validate status transition before applying
        if "status" in update_data:
            validate_transition(
                TransactionLifecycle, old_status, update_data["status"], "transaction"
            )

        for key, value in update_data.items():
            setattr(instance, key, value)

        # Update tags if provided
        if data.tags is not None:
            await db.execute(
                delete(TransactionTag).where(TransactionTag.transaction_id == entity_id)
            )
            for tag_name in data.tags:
                db.add(TransactionTag(transaction_id=entity_id, tag=tag_name))

        # Balance delta adjustment
        if old_status == "completed":
            # Reverse old delta
            old_delta = _balance_delta(old_type, old_amount)
            await _adjust_wallet_balance(db, old_wallet_id, -old_delta)
            await _adjust_wallet_balance(db, old_wallet_id, old_fee)

        if instance.status == "completed":
            # Apply new delta
            new_delta = _balance_delta(instance.type, instance.amount)
            await _adjust_wallet_balance(db, instance.wallet_id, new_delta)
            if instance.fee:
                await _adjust_wallet_balance(db, instance.wallet_id, -instance.fee)

        await db.flush()
        await db.refresh(instance)

        if old_status != instance.status:
            await emit_state_changed(
                "finance", "transaction", entity_id, old_status, instance.status, user_id
            )

        # Audit diff
        new_snapshot = self._snapshot(instance)
        changes = self._compute_diff(old_snapshot, new_snapshot)
        if changes:
            await self._record_audit(
                db,
                action="updated",
                entity_id=entity_id,
                user_id=user_id or instance.created_by,
                space_id=instance.space_id,
                changes=changes,
            )

        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSACTION_UPDATED,
                data={
                    "transaction_id": entity_id,
                    "type": instance.type,
                    "amount": str(instance.amount),
                },
                source="finance",
                user_id=user_id or instance.created_by,
            )
        )
        return instance

    async def delete(self, db: AsyncSession, entity_id: str, user_id: str | None = None) -> bool:
        instance = await self.get(db, entity_id)
        if not instance:
            return False

        # Reverse balance delta before soft delete
        if instance.status == "completed":
            delta = _balance_delta(instance.type, instance.amount)
            await _adjust_wallet_balance(db, instance.wallet_id, -delta)
            if instance.fee:
                await _adjust_wallet_balance(db, instance.wallet_id, instance.fee)

        snapshot = self._snapshot(instance)
        txn_id = instance.id
        txn_user_id = user_id or instance.created_by

        # Soft delete
        instance.deleted_at = datetime.now(UTC)
        await db.flush()

        await self._record_audit(
            db,
            action="deleted",
            entity_id=txn_id,
            user_id=txn_user_id,
            space_id=instance.space_id,
            snapshot=snapshot,
        )

        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSACTION_DELETED,
                data={"transaction_id": txn_id},
                source="finance",
                user_id=txn_user_id,
            )
        )
        return True

    async def restore(
        self, db: AsyncSession, entity_id: str, user_id: str | None = None
    ) -> Transaction | None:
        """Restore a soft-deleted transaction and re-apply balance delta."""
        instance = await db.get(Transaction, entity_id)
        if not instance or instance.deleted_at is None:
            return None

        instance.deleted_at = None
        await db.flush()

        # Re-apply balance delta
        if instance.status == "completed":
            delta = _balance_delta(instance.type, instance.amount)
            await _adjust_wallet_balance(db, instance.wallet_id, delta)
            if instance.fee:
                await _adjust_wallet_balance(db, instance.wallet_id, -instance.fee)

        await db.flush()
        await db.refresh(instance)

        await self._record_audit(
            db,
            action="restored",
            entity_id=entity_id,
            user_id=user_id or instance.created_by,
            space_id=instance.space_id,
            snapshot=self._snapshot(instance),
        )
        return instance

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
        year_month: str | None = None,
        txn_type: str | None = None,
        category_id: str | None = None,
        wallet_id: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> PaginatedResponse[TransactionResponse]:
        p = pagination or PaginationParams()
        base = select(Transaction).where(
            Transaction.space_id == space_id,
            Transaction.deleted_at == None,  # noqa: E711
        )
        base = apply_privacy_filter(base, Transaction, user_id)

        if year_month:
            base = base.where(func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month)
        if txn_type:
            base = base.where(Transaction.type == txn_type)
        if category_id:
            base = base.where(Transaction.category_id == category_id)
        if wallet_id:
            base = base.where(Transaction.wallet_id == wallet_id)
        if tag:
            base = base.where(
                Transaction.id.in_(
                    select(TransactionTag.transaction_id).where(TransactionTag.tag == tag)
                )
            )
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    Transaction.description.ilike(pattern),
                    Transaction.merchant.ilike(pattern),
                )
            )

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(Transaction.transacted_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[Transaction] = (await db.execute(q)).scalars().unique().all()
        return PaginatedResponse[TransactionResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Subscription Service ========================


class SubscriptionService(
    BaseCRUDService[Subscription, SubscriptionCreate, SubscriptionUpdate, SubscriptionResponse]
):
    model = Subscription
    audit_module = "finance"
    audit_entity_type = "subscriptions"

    def to_response(self, instance: Subscription) -> SubscriptionResponse:
        return SubscriptionResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            icon_url=instance.icon_url,
            name=instance.name,
            amount=instance.amount,
            currency=instance.currency,
            billing_cycle=instance.billing_cycle,
            billing_day=instance.billing_day,
            category_id=instance.category_id,
            wallet_id=instance.wallet_id,
            payment_method=instance.payment_method,
            payment_detail=instance.payment_detail,
            start_date=instance.start_date,
            end_date=instance.end_date,
            status=instance.status,
            next_billing=instance.next_billing,
            notes=instance.notes,
            reminder_days=instance.reminder_days,
            tags=instance.tags or [],
            is_private=instance.is_private,
        )

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
        status: str | None = None,
    ) -> PaginatedResponse[SubscriptionResponse]:
        p = pagination or PaginationParams()
        base = select(Subscription).where(
            Subscription.space_id == space_id,
            Subscription.deleted_at == None,  # noqa: E711
        )
        base = apply_privacy_filter(base, Subscription, user_id)
        if status:
            base = base.where(Subscription.status == status)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = base.order_by(Subscription.name).offset((p.page - 1) * p.page_size).limit(p.page_size)
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[SubscriptionResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Installment Plan Service ========================


class InstallmentPlanService(
    BaseCRUDService[
        InstallmentPlan, InstallmentPlanCreate, InstallmentPlanUpdate, InstallmentPlanResponse
    ]
):
    model = InstallmentPlan
    audit_module = "finance"
    audit_entity_type = "installment_plans"

    def to_response(self, instance: InstallmentPlan) -> InstallmentPlanResponse:
        return InstallmentPlanResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            icon_url=instance.icon_url,
            description=instance.description,
            total_amount=instance.total_amount,
            currency=instance.currency,
            num_installments=instance.num_installments,
            installment_amount=instance.installment_amount,
            interest_rate=instance.interest_rate,
            billing_day=instance.billing_day,
            fee_type=instance.fee_type,
            fee_per_installment=instance.fee_per_installment,
            merchant=instance.merchant,
            category_id=instance.category_id,
            wallet_id=instance.wallet_id,
            payment_method=instance.payment_method,
            payment_detail=instance.payment_detail,
            start_date=instance.start_date,
            end_date=instance.end_date,
            status=instance.status,
            tags=instance.tags or [],
            is_private=instance.is_private,
        )

    def after_create(self, instance: InstallmentPlan) -> None:
        # Fire-and-forget: after_create is sync, so schedule the coroutine
        import asyncio

        _task = asyncio.ensure_future(  # noqa: RUF006
            event_bus.publish(
                Event(
                    type=FinanceEvents.INSTALLMENT_CREATED,
                    data={"plan_id": instance.id, "num_installments": instance.num_installments},
                    source="finance",
                    user_id=instance.created_by,
                )
            )
        )

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
        status: str | None = None,
    ) -> PaginatedResponse[InstallmentPlanResponse]:
        p = pagination or PaginationParams()
        base = select(InstallmentPlan).where(
            InstallmentPlan.space_id == space_id,
            InstallmentPlan.deleted_at == None,  # noqa: E711
        )
        base = apply_privacy_filter(base, InstallmentPlan, user_id)
        if status:
            base = base.where(InstallmentPlan.status == status)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(InstallmentPlan.start_date.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[InstallmentPlanResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Budget Service ========================


class BudgetService(BaseCRUDService[Budget, BudgetCreate, BudgetUpdate, BudgetResponse]):
    model = Budget
    audit_module = "finance"
    audit_entity_type = "budgets"

    def to_response(
        self,
        instance: Budget,
        spent: Decimal | None = None,
        cat_name: str | None = None,
    ) -> BudgetResponse:
        spent_amount = spent or Decimal("0")
        budget_amt = instance.budget_amount or Decimal("0")
        remaining = budget_amt - spent_amount
        used_pct = float(spent_amount / budget_amt * 100) if budget_amt else 0.0
        return BudgetResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            year_month=instance.year_month,
            category_id=instance.category_id,
            category_name=cat_name,
            budget_amount=instance.budget_amount,
            savings_target=instance.savings_target,
            spent_amount=spent_amount,
            remaining_amount=remaining,
            used_pct=round(used_pct, 1),
            is_private=instance.is_private,
        )

    async def upsert(
        self,
        db: AsyncSession,
        space_id: str,
        data: BudgetCreate,
        user_id: str | None = None,
    ) -> Budget:
        """Create or update budget for a year_month + category_id combination."""
        q = select(Budget).where(
            Budget.space_id == space_id,
            Budget.year_month == data.year_month,
            Budget.deleted_at == None,  # noqa: E711
        )
        if data.category_id:
            q = q.where(Budget.category_id == data.category_id)
        else:
            q = q.where(Budget.category_id == None)  # noqa: E711

        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            existing.budget_amount = data.budget_amount
            if data.savings_target is not None:
                existing.savings_target = data.savings_target
            existing.is_private = data.is_private
            await db.flush()
            await db.refresh(existing)
            return existing
        return await super().create(db, space_id, data, user_id)

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        user_id: str | None = None,
        year_month: str | None = None,
    ) -> PaginatedResponse[BudgetResponse]:
        p = pagination or PaginationParams()
        base = select(Budget).where(
            Budget.space_id == space_id,
            Budget.deleted_at == None,  # noqa: E711
        )
        base = apply_privacy_filter(base, Budget, user_id)
        if year_month:
            base = base.where(Budget.year_month == year_month)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(Budget.year_month.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()

        # Compute actual spending per category for the relevant months
        ym_set = {r.year_month for r in rows}
        spending_map: dict[tuple[str, str | None], Decimal] = {}
        cat_name_map: dict[str, str] = {}
        for ym in ym_set:
            spending_q = (
                select(
                    Transaction.category_id,
                    func.coalesce(Category.name, "未分類").label("cat_name"),
                    func.sum(Transaction.amount).label("total"),
                )
                .outerjoin(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.space_id == space_id,
                    Transaction.type == "expense",
                    Transaction.status == "completed",
                    func.to_char(Transaction.transacted_at, "YYYY-MM") == ym,
                )
                .group_by(Transaction.category_id, Category.name)
            )
            spending_q = apply_privacy_filter(spending_q, Transaction, user_id)
            spending_rows = (await db.execute(spending_q)).all()
            for sr in spending_rows:
                spending_map[(ym, sr.category_id)] = sr.total or Decimal("0")
                if sr.category_id:
                    cat_name_map[sr.category_id] = sr.cat_name

            # Total spending for budgets without category
            total_spending = sum((sr.total or Decimal("0")) for sr in spending_rows)
            spending_map[(ym, None)] = total_spending

        items = []
        for r in rows:
            spent = spending_map.get((r.year_month, r.category_id), Decimal("0"))
            cat_name = cat_name_map.get(r.category_id, None) if r.category_id else None
            items.append(self.to_response(r, spent=spent, cat_name=cat_name))

        return PaginatedResponse[BudgetResponse](
            items=items,
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get_status(
        self,
        db: AsyncSession,
        space_id: str,
        year_month: str,
        user_id: str | None = None,
    ) -> dict:
        """Return budget vs actual spending for a given month."""
        budgets_q = select(Budget).where(
            Budget.space_id == space_id,
            Budget.year_month == year_month,
            Budget.deleted_at == None,  # noqa: E711
        )
        budgets_q = apply_privacy_filter(budgets_q, Budget, user_id)
        budgets = (await db.execute(budgets_q)).scalars().all()

        # Actual spending by category for the month (exclude deleted transactions)
        spending_q = (
            select(
                Transaction.category_id,
                func.sum(Transaction.amount).label("total"),
            )
            .where(
                Transaction.space_id == space_id,
                Transaction.type == "expense",
                Transaction.status == "completed",
                Transaction.deleted_at == None,  # noqa: E711
                func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
            )
            .group_by(Transaction.category_id)
        )
        spending_q = apply_privacy_filter(spending_q, Transaction, user_id)
        spending_rows = (await db.execute(spending_q)).all()
        spending_map = {row.category_id: row.total for row in spending_rows}

        items = []
        for b in budgets:
            actual = spending_map.get(b.category_id, Decimal("0"))
            items.append(
                {
                    "budget_id": b.id,
                    "category_id": b.category_id,
                    "year_month": b.year_month,
                    "budget_amount": b.budget_amount,
                    "actual_spending": actual,
                    "remaining": b.budget_amount - actual,
                    "percentage": float(actual / b.budget_amount * 100) if b.budget_amount else 0,
                    "exceeded": actual > b.budget_amount,
                }
            )

            if actual > b.budget_amount:
                await event_bus.publish(
                    Event(
                        type=FinanceEvents.BUDGET_EXCEEDED,
                        data={
                            "budget_id": b.id,
                            "category_id": b.category_id,
                            "budget_amount": str(b.budget_amount),
                            "actual": str(actual),
                        },
                        source="finance",
                        user_id=user_id,
                    )
                )

        return {"year_month": year_month, "budgets": items}


# ======================== Transfer Service ========================


class TransferService:
    """Handle wallet-to-wallet transfers with deadlock prevention."""

    async def transfer(
        self,
        db: AsyncSession,
        space_id: str,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: Decimal,
        currency: str = "TWD",
        description: str | None = None,
        payment_method: str = "bank_transfer",
        payment_detail: str | None = None,
        fee: Decimal = Decimal("0"),
        transacted_at: datetime | None = None,
        user_id: str | None = None,
    ) -> tuple[Transaction, Transaction]:
        """Execute a transfer between two wallets in the same DB transaction.

        SELECT FOR UPDATE sorted by wallet_id to prevent deadlocks.
        """
        if from_wallet_id == to_wallet_id:
            raise BadRequestError(
                "Cannot transfer to the same wallet", code="finance.same_wallet_transfer"
            )
        if amount <= 0:
            raise BadRequestError("Transfer amount must be positive", code="finance.invalid_amount")

        txn_at = transacted_at or datetime.now(UTC)

        # Lock wallets in sorted order to prevent deadlocks
        sorted_ids = sorted([from_wallet_id, to_wallet_id])
        for wid in sorted_ids:
            w = await db.get(Wallet, wid, with_for_update=True)
            if not w:
                raise NotFoundError(f"Wallet {wid} not found", code="finance.wallet_not_found")

        # Create outgoing transaction
        out_txn = Transaction(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            type="transfer",
            amount=amount,
            currency=currency,
            description=description or "Transfer to wallet",
            payment_method=payment_method,
            payment_detail=payment_detail,
            wallet_id=from_wallet_id,
            transfer_to_wallet_id=to_wallet_id,
            fee=fee,
            transacted_at=txn_at,
            status="completed",
        )
        # Create incoming transaction
        in_txn = Transaction(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            type="transfer",
            amount=amount,
            currency=currency,
            description=description or "Transfer from wallet",
            payment_method=payment_method,
            payment_detail=payment_detail,
            wallet_id=to_wallet_id,
            transfer_to_wallet_id=from_wallet_id,
            fee=Decimal("0"),
            transacted_at=txn_at,
            status="completed",
        )

        # Link paired transactions
        out_txn.paired_transaction_id = in_txn.id
        in_txn.paired_transaction_id = out_txn.id

        db.add(out_txn)
        db.add(in_txn)

        # Update balances atomically
        await _adjust_wallet_balance(db, from_wallet_id, -(amount + fee))
        await _adjust_wallet_balance(db, to_wallet_id, amount)

        await db.flush()

        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSFER_COMPLETED,
                data={
                    "from_wallet_id": from_wallet_id,
                    "to_wallet_id": to_wallet_id,
                    "amount": str(amount),
                    "out_txn_id": out_txn.id,
                    "in_txn_id": in_txn.id,
                },
                source="finance",
                user_id=user_id,
            )
        )

        return out_txn, in_txn


# ======================== Summary Service ========================


class SummaryService:
    """Monthly summary and category breakdown."""

    async def monthly_summary(
        self,
        db: AsyncSession,
        space_id: str,
        year_month: str,
        user_id: str | None = None,
    ) -> MonthlySummaryResponse:
        base = select(Transaction).where(
            Transaction.space_id == space_id,
            Transaction.status == "completed",
            Transaction.deleted_at == None,  # noqa: E711
            func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
        )
        base = apply_privacy_filter(base, Transaction, user_id)

        # Totals by type
        totals_q = (
            select(
                Transaction.type,
                func.sum(Transaction.amount).label("total"),
                func.count().label("cnt"),
            )
            .where(
                Transaction.space_id == space_id,
                Transaction.status == "completed",
                Transaction.deleted_at == None,  # noqa: E711
                func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
            )
            .group_by(Transaction.type)
        )
        totals_q = apply_privacy_filter(totals_q, Transaction, user_id)
        totals = (await db.execute(totals_q)).all()

        income = Decimal("0")
        expense = Decimal("0")
        count = 0
        for row in totals:
            if row.type == "income":
                income = row.total or Decimal("0")
            elif row.type == "expense":
                expense = row.total or Decimal("0")
            count += row.cnt

        # Category breakdown (expenses only)
        cat_q = (
            select(
                Transaction.category_id,
                func.coalesce(Category.name, "未分類").label("category_name"),
                Category.icon.label("category_icon"),
                func.sum(Transaction.amount).label("total"),
                func.count().label("cnt"),
            )
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.space_id == space_id,
                Transaction.type == "expense",
                Transaction.status == "completed",
                Transaction.deleted_at == None,  # noqa: E711
                func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
            )
            .group_by(Transaction.category_id, Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        cat_q = apply_privacy_filter(cat_q, Transaction, user_id)
        cat_rows = (await db.execute(cat_q)).all()

        breakdown = []
        for row in cat_rows:
            pct = float(row.total / expense * 100) if expense else 0.0
            breakdown.append(
                CategoryBreakdown(
                    category_id=row.category_id,
                    category_name=row.category_name,
                    category_icon=row.category_icon,
                    amount=row.total,
                    count=row.cnt,
                    pct=round(pct, 1),
                )
            )

        # Wallet overview: balance + change for this month
        wallet_q = select(Wallet).where(
            Wallet.space_id == space_id,
            Wallet.is_active == True,  # noqa: E712
        )
        wallet_q = apply_privacy_filter(wallet_q, Wallet, user_id)
        wallets = (await db.execute(wallet_q)).scalars().all()

        wallet_overview = []
        for w in wallets:
            # Change = income - expense for this wallet in this month
            change_q = (
                select(
                    Transaction.type,
                    func.coalesce(func.sum(Transaction.amount), Decimal("0")).label("total"),
                )
                .where(
                    Transaction.wallet_id == w.id,
                    Transaction.status == "completed",
                    func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
                )
                .group_by(Transaction.type)
            )
            change_rows = (await db.execute(change_q)).all()
            change = Decimal("0")
            for cr in change_rows:
                if cr.type == "income":
                    change += cr.total or Decimal("0")
                elif cr.type in ("expense", "transfer"):
                    change -= cr.total or Decimal("0")
            wallet_overview.append(
                WalletOverviewItem(
                    wallet_id=w.id,
                    wallet_name=w.name,
                    wallet_type=w.type,
                    current_balance=w.current_balance,
                    change=change,
                )
            )

        return MonthlySummaryResponse(
            year_month=year_month,
            total_income=income,
            total_expense=expense,
            net=income - expense,
            transaction_count=count,
            category_breakdown=breakdown,
            wallet_overview=wallet_overview,
        )

    async def monthly_trends(
        self,
        db: AsyncSession,
        space_id: str,
        months: int = 6,
        user_id: str | None = None,
    ) -> list[MonthlyTrendResponse]:
        """Return income/expense/net for the last N months."""
        from datetime import date as _date
        from datetime import timedelta

        today = _date.today()
        results = []
        for i in range(months - 1, -1, -1):
            # Calculate year_month for i months ago
            d = today.replace(day=1)
            for _ in range(i):
                d = (d - timedelta(days=1)).replace(day=1)
            ym = d.strftime("%Y-%m")

            totals_q = (
                select(
                    Transaction.type,
                    func.coalesce(func.sum(Transaction.amount), Decimal("0")).label("total"),
                )
                .where(
                    Transaction.space_id == space_id,
                    Transaction.status == "completed",
                    func.to_char(Transaction.transacted_at, "YYYY-MM") == ym,
                )
                .group_by(Transaction.type)
            )
            totals_q = apply_privacy_filter(totals_q, Transaction, user_id)
            rows = (await db.execute(totals_q)).all()

            inc = Decimal("0")
            exp = Decimal("0")
            for row in rows:
                if row.type == "income":
                    inc = row.total or Decimal("0")
                elif row.type == "expense":
                    exp = row.total or Decimal("0")

            results.append(
                MonthlyTrendResponse(
                    year_month=ym,
                    income=inc,
                    expense=exp,
                    net=inc - exp,
                )
            )
        return results

    async def net_worth(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> list[NetWorthPointResponse]:
        """Return current net worth grouped by wallet type."""
        from datetime import date as _date

        q = select(
            Wallet.type,
            func.sum(Wallet.current_balance).label("total"),
        ).where(
            Wallet.space_id == space_id,
            Wallet.is_active == True,  # noqa: E712
        )
        q = apply_privacy_filter(q, Wallet, user_id)
        q = q.group_by(Wallet.type)
        rows = (await db.execute(q)).all()

        type_map: dict[str, Decimal] = {}
        grand_total = Decimal("0")
        for row in rows:
            type_map[row.type] = row.total or Decimal("0")
            grand_total += row.total or Decimal("0")

        return [
            NetWorthPointResponse(
                date=_date.today().isoformat(),
                total=grand_total,
                bank=type_map.get("bank_account", Decimal("0")),
                cash=type_map.get("cash", Decimal("0")),
                e_wallet=type_map.get("e_wallet", Decimal("0")),
                investment=type_map.get("investment", Decimal("0")),
                credit_card=type_map.get("credit_card", Decimal("0")),
            )
        ]


# ======================== Module-Level Singletons ========================

wallet_service = WalletService()
category_service = CategoryService()
transaction_service = TransactionService()
subscription_service = SubscriptionService()
installment_plan_service = InstallmentPlanService()
budget_service = BudgetService()
transfer_service = TransferService()
summary_service = SummaryService()
