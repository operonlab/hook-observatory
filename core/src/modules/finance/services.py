"""Finance services — CRUD + balance management + reconciliation.

This is the PUBLIC API of the finance module.
Other modules import from here, never from models.py.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, delete, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import FinanceEvents
from src.modules.finance.lifecycle import TransactionLifecycle
from src.shared.cache import cached
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
    GapAnalysisResponse,
    GlobalSnapshotResponse,
    GlobalSnapshotSummary,
    InstallmentPlanCreate,
    InstallmentPlanResponse,
    InstallmentPlanUpdate,
    MonthlySummaryResponse,
    MonthlyTrendResponse,
    NetWorthPointResponse,
    ReconcileResponse,
    SnapshotDiffResponse,
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

logger = logging.getLogger(__name__)

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


# ======================== Batch Helpers ========================


async def _batch_balance_components(
    db: AsyncSession,
    wallet_ids: list[str],
) -> dict[str, tuple[Decimal, Decimal, Decimal, Decimal]]:
    """Batch-compute balance components for multiple wallets in 2 queries.

    Returns ``{wallet_id: (income, expense, transfer_in, fees)}``.
    """
    if not wallet_ids:
        return {}

    zero = Decimal("0")
    result: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
        wid: (zero, zero, zero, zero) for wid in wallet_ids
    }

    # Query 1: income / expense / fees grouped by wallet
    agg_q = (
        select(
            Transaction.wallet_id,
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == "income", Transaction.amount),
                        else_=literal_column("0"),
                    )
                ),
                0,
            ).label("income"),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type.in_(["expense", "transfer"]), Transaction.amount),
                        else_=literal_column("0"),
                    )
                ),
                0,
            ).label("expense"),
            func.coalesce(func.sum(Transaction.fee), 0).label("fees"),
        )
        .where(
            Transaction.wallet_id.in_(wallet_ids),
            Transaction.status == "completed",
            Transaction.deleted_at == None,  # noqa: E711
        )
        .group_by(Transaction.wallet_id)
    )
    for row in (await db.execute(agg_q)).all():
        inc = Decimal(str(row.income))
        exp = Decimal(str(row.expense))
        fees = Decimal(str(row.fees))
        result[row.wallet_id] = (inc, exp, zero, fees)

    # Query 2: transfer-in grouped by target wallet
    xfer_q = (
        select(
            Transaction.transfer_to_wallet_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("transfer_in"),
        )
        .where(
            Transaction.transfer_to_wallet_id.in_(wallet_ids),
            Transaction.type == "transfer",
            Transaction.status == "completed",
            Transaction.deleted_at == None,  # noqa: E711
        )
        .group_by(Transaction.transfer_to_wallet_id)
    )
    for row in (await db.execute(xfer_q)).all():
        wid = row.transfer_to_wallet_id
        inc, exp, _, fees = result[wid]
        result[wid] = (inc, exp, Decimal(str(row.transfer_in)), fees)

    return result


async def _batch_max_versions(
    db: AsyncSession,
    wallet_ids: list[str],
) -> dict[str, int]:
    """Get max snapshot version per wallet in a single query."""
    if not wallet_ids:
        return {}
    q = (
        select(
            WalletSnapshot.wallet_id,
            func.coalesce(func.max(WalletSnapshot.version), 0).label("max_ver"),
        )
        .where(WalletSnapshot.wallet_id.in_(wallet_ids))
        .group_by(WalletSnapshot.wallet_id)
    )
    rows = (await db.execute(q)).all()
    versions = {row.wallet_id: row.max_ver for row in rows}
    # Wallets with no snapshots default to 0
    return {wid: versions.get(wid, 0) for wid in wallet_ids}


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
    """Atomic delta update on wallet current_balance.

    Cash wallets enforce a hard floor of 0 — cannot go negative.
    """
    if delta < 0:
        wallet = await db.get(Wallet, wallet_id)
        if wallet and wallet.type == "cash":
            projected = wallet.current_balance + delta
            if projected < 0:
                raise BadRequestError(
                    f"現金錢包「{wallet.name}」餘額不足："  # noqa: RUF001
                    f"目前 ${wallet.current_balance:,.0f}，"  # noqa: RUF001
                    f"需要 ${abs(delta):,.0f}",
                    code="finance.cash_insufficient",
                )
    await db.execute(
        update(Wallet)
        .where(Wallet.id == wallet_id)
        .values(current_balance=Wallet.current_balance + delta)
    )


# ======================== Balance Calculation Helpers ========================


async def _calc_balance_components(
    db: AsyncSession,
    wallet_id: str,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Compute balance components for a wallet, optionally within a time range.

    Returns (income_sum, expense_sum, transfer_in, fee_sum).
    Net delta = income - expense + transfer_in - fee.
    """
    txn_filter = [
        Transaction.wallet_id == wallet_id,
        Transaction.status == "completed",
        Transaction.deleted_at == None,  # noqa: E711
    ]
    if from_time is not None:
        txn_filter.append(Transaction.transacted_at > from_time)
    if to_time is not None:
        txn_filter.append(Transaction.transacted_at <= to_time)

    # Single aggregation query with CASE WHEN
    agg_q = select(
        func.coalesce(
            func.sum(
                case((Transaction.type == "income", Transaction.amount), else_=literal_column("0"))
            ),
            0,
        ).label("income"),
        func.coalesce(
            func.sum(
                case(
                    (Transaction.type.in_(["expense", "transfer"]), Transaction.amount),
                    else_=literal_column("0"),
                )
            ),
            0,
        ).label("expense"),
        func.coalesce(func.sum(Transaction.fee), 0).label("fees"),
    ).where(*txn_filter)
    row = (await db.execute(agg_q)).one()

    # Transfer-in is a separate query (different wallet_id column)
    transfer_filter = [
        Transaction.transfer_to_wallet_id == wallet_id,
        Transaction.type == "transfer",
        Transaction.status == "completed",
        Transaction.deleted_at == None,  # noqa: E711
    ]
    if from_time is not None:
        transfer_filter.append(Transaction.transacted_at > from_time)
    if to_time is not None:
        transfer_filter.append(Transaction.transacted_at <= to_time)

    transfer_in = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(*transfer_filter)
        )
    ).scalar_one()

    return Decimal(str(row.income)), Decimal(str(row.expense)), transfer_in, Decimal(str(row.fees))


async def _compute_period_delta(
    db: AsyncSession, wallet_id: str, from_time: datetime, to_time: datetime
) -> tuple[Decimal, list]:
    """Compute net balance change from transactions in a time period.
    Returns (net_delta, transaction_list).
    """
    income, expense, transfer_in, fees = await _calc_balance_components(
        db, wallet_id, from_time, to_time
    )
    net_delta = income - expense + transfer_in - fees

    # Get transaction list
    txn_filter = [
        Transaction.wallet_id == wallet_id,
        Transaction.status == "completed",
        Transaction.deleted_at == None,  # noqa: E711
        Transaction.transacted_at > from_time,
        Transaction.transacted_at <= to_time,
    ]
    txns = (
        (
            await db.execute(
                select(Transaction).where(*txn_filter).order_by(Transaction.transacted_at)
            )
        )
        .scalars()
        .all()
    )

    return net_delta, txns


# ======================== Wallet Service ========================


class WalletService(BaseCRUDService[Wallet, WalletCreate, WalletUpdate, WalletResponse]):
    model = Wallet
    audit_module = "finance"
    audit_entity_type = "wallets"
    event_types = {
        "created": FinanceEvents.WALLET_CREATED,
        "updated": FinanceEvents.WALLET_UPDATED,
        "deleted": FinanceEvents.WALLET_DELETED,
    }

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

    @cached("finance", "list_wallets", ttl=300, key_params=("space_id",))
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

        # Determine next version for this wallet
        max_version = (
            await db.execute(
                select(func.coalesce(func.max(WalletSnapshot.version), 0)).where(
                    WalletSnapshot.wallet_id == wallet_id
                )
            )
        ).scalar_one()
        next_version = max_version + 1

        snapshot = WalletSnapshot(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            wallet_id=wallet_id,
            synced_balance=data.synced_balance,
            calculated_balance=calculated,
            snapshot_type="reconciliation",
            notes=data.notes,
            version=next_version,
            metadata_json={
                "wallet_name": wallet.name,
                "wallet_type": wallet.type,
                "currency": wallet.currency,
                "is_active": wallet.is_active,
            },
        )
        db.add(snapshot)

        wallet.current_balance = data.synced_balance
        wallet.last_synced_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(snapshot)

        try:
            await event_bus.publish(
                Event(
                    type=FinanceEvents.WALLET_SYNCED,
                    data={"wallet_id": wallet_id, "synced_balance": str(data.synced_balance)},
                    source="finance",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("Failed to publish WALLET_SYNCED event", exc_info=True)

        return self._snapshot_to_response(snapshot)

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

        income, expense, transfer_in, fees = await _calc_balance_components(db, wallet_id)
        calculated = wallet.initial_balance + income - expense + transfer_in - fees

        txn_count = (
            await db.execute(
                select(func.count()).where(
                    Transaction.wallet_id == wallet_id,
                    Transaction.status == "completed",
                    Transaction.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

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

    # --- Phase D: Snapshot Versioning ---

    def _snapshot_to_response(self, s: WalletSnapshot) -> WalletSnapshotResponse:
        return WalletSnapshotResponse(
            id=s.id,
            space_id=s.space_id,
            created_by=s.created_by,
            created_at=s.created_at,
            updated_at=s.updated_at,
            wallet_id=s.wallet_id,
            synced_balance=s.synced_balance,
            calculated_balance=s.calculated_balance,
            difference=s.synced_balance - s.calculated_balance,
            snapshot_type=s.snapshot_type,
            notes=s.notes,
            synced_at=s.synced_at,
            version=s.version,
            batch_id=s.batch_id,
            metadata_json=s.metadata_json,
        )

    async def list_snapshots(
        self,
        db: AsyncSession,
        wallet_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[WalletSnapshotResponse]:
        """List snapshot history for a wallet (version DESC)."""
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise NotFoundError("Wallet not found", code="finance.wallet_not_found")

        p = pagination or PaginationParams()
        base = select(WalletSnapshot).where(
            WalletSnapshot.wallet_id == wallet_id,
            WalletSnapshot.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(WalletSnapshot.version.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[WalletSnapshotResponse](
            items=[self._snapshot_to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def _get_snapshot_pair(
        self,
        db: AsyncSession,
        wallet_id: str,
        from_v: int,
        to_v: int,
    ) -> tuple[WalletSnapshot, WalletSnapshot]:
        """Fetch two snapshot versions in a single query with soft-delete filter."""
        rows = (
            (
                await db.execute(
                    select(WalletSnapshot).where(
                        WalletSnapshot.wallet_id == wallet_id,
                        WalletSnapshot.version.in_([from_v, to_v]),
                        WalletSnapshot.deleted_at == None,  # noqa: E711
                    )
                )
            )
            .scalars()
            .all()
        )
        snap_map = {s.version: s for s in rows}
        if from_v not in snap_map:
            raise NotFoundError(
                f"Snapshot version {from_v} not found",
                code="finance.snapshot_not_found",
            )
        if to_v not in snap_map:
            raise NotFoundError(
                f"Snapshot version {to_v} not found",
                code="finance.snapshot_not_found",
            )
        return snap_map[from_v], snap_map[to_v]

    async def diff_snapshots(
        self,
        db: AsyncSession,
        wallet_id: str,
        from_v: int,
        to_v: int,
    ) -> SnapshotDiffResponse:
        """Compute diff between two snapshot versions."""
        from_snap, to_snap = await self._get_snapshot_pair(db, wallet_id, from_v, to_v)

        balance_delta = to_snap.synced_balance - from_snap.synced_balance
        delta_pct = (
            float(balance_delta / from_snap.synced_balance * 100)
            if from_snap.synced_balance
            else 0.0
        )
        period_days = (to_snap.synced_at - from_snap.synced_at).days

        return SnapshotDiffResponse(
            wallet_id=wallet_id,
            from_version=from_v,
            to_version=to_v,
            from_synced_balance=from_snap.synced_balance,
            to_synced_balance=to_snap.synced_balance,
            balance_delta=balance_delta,
            delta_pct=round(delta_pct, 2),
            from_synced_at=from_snap.synced_at,
            to_synced_at=to_snap.synced_at,
            period_days=period_days,
        )

    async def gap_analysis(
        self,
        db: AsyncSession,
        wallet_id: str,
        from_v: int,
        to_v: int,
    ) -> GapAnalysisResponse:
        """Sandwich reconciliation: snapshot delta vs transaction sum."""
        from_snap, to_snap = await self._get_snapshot_pair(db, wallet_id, from_v, to_v)

        snapshot_delta = to_snap.synced_balance - from_snap.synced_balance
        transaction_sum, txns = await _compute_period_delta(
            db, wallet_id, from_snap.synced_at, to_snap.synced_at
        )
        gap = snapshot_delta - transaction_sum
        gap_pct = float(gap / snapshot_delta * 100) if snapshot_delta else 0.0
        is_reconciled = abs(gap) < 1  # 1 unit tolerance

        txn_responses = [transaction_service.to_response(t) for t in txns]

        return GapAnalysisResponse(
            wallet_id=wallet_id,
            from_version=from_v,
            to_version=to_v,
            snapshot_delta=snapshot_delta,
            transaction_sum=transaction_sum,
            gap=gap,
            gap_pct=round(gap_pct, 2),
            is_reconciled=is_reconciled,
            transactions=txn_responses,
            from_synced_at=from_snap.synced_at,
            to_synced_at=to_snap.synced_at,
        )

    async def create_global_snapshot(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> GlobalSnapshotResponse:
        """Create snapshots for all active wallets with a shared batch_id."""
        batch_id = _uuid7_hex()

        wallets_q = select(Wallet).where(
            Wallet.space_id == space_id,
            Wallet.is_active == True,  # noqa: E712
            Wallet.deleted_at == None,  # noqa: E711
        )
        wallets = (await db.execute(wallets_q)).scalars().all()

        snapshots = []
        total_net_worth = Decimal("0")
        now = datetime.now(UTC)

        # Batch: 3 queries total instead of 3N
        wallet_ids = [w.id for w in wallets]
        balance_map = await _batch_balance_components(db, wallet_ids)
        version_map = await _batch_max_versions(db, wallet_ids)

        for wallet in wallets:
            income, expense, transfer_in, fees = balance_map[wallet.id]
            calculated = wallet.initial_balance + income - expense + transfer_in - fees
            max_version = version_map[wallet.id]

            snapshot = WalletSnapshot(
                id=_uuid7_hex(),
                space_id=space_id,
                created_by=user_id,
                wallet_id=wallet.id,
                synced_balance=wallet.current_balance,
                calculated_balance=calculated,
                snapshot_type="reconciliation",
                version=max_version + 1,
                batch_id=batch_id,
                synced_at=now,
                metadata_json={
                    "wallet_name": wallet.name,
                    "wallet_type": wallet.type,
                    "currency": wallet.currency,
                    "is_active": wallet.is_active,
                    "global_snapshot": True,
                },
            )
            db.add(snapshot)
            snapshots.append(snapshot)
            total_net_worth += wallet.current_balance

        await db.flush()

        # Refresh all snapshots to get computed columns
        for s in snapshots:
            await db.refresh(s)

        try:
            await event_bus.publish(
                Event(
                    type=FinanceEvents.GLOBAL_SNAPSHOT_CREATED,
                    data={
                        "batch_id": batch_id,
                        "snapshot_count": len(snapshots),
                        "total_net_worth": str(total_net_worth),
                        "space_id": space_id,
                    },
                    source="finance",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("Failed to publish GLOBAL_SNAPSHOT_CREATED event", exc_info=True)

        return GlobalSnapshotResponse(
            batch_id=batch_id,
            snapshot_count=len(snapshots),
            total_net_worth=total_net_worth,
            snapshots=[self._snapshot_to_response(s) for s in snapshots],
            created_at=now,
        )

    async def list_global_snapshots(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[GlobalSnapshotSummary]:
        """List global snapshot batches."""
        p = pagination or PaginationParams()

        # Aggregate by batch_id
        base = (
            select(
                WalletSnapshot.batch_id,
                func.count().label("snapshot_count"),
                func.sum(WalletSnapshot.synced_balance).label("total_net_worth"),
                func.min(WalletSnapshot.created_at).label("created_at"),
            )
            .where(
                WalletSnapshot.space_id == space_id,
                WalletSnapshot.batch_id != None,  # noqa: E711
                WalletSnapshot.deleted_at == None,  # noqa: E711
            )
            .group_by(WalletSnapshot.batch_id)
        )

        # Count total batches
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(func.min(WalletSnapshot.created_at).desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).all()

        items = [
            GlobalSnapshotSummary(
                batch_id=row.batch_id,
                snapshot_count=row.snapshot_count,
                total_net_worth=row.total_net_worth or Decimal("0"),
                created_at=row.created_at,
            )
            for row in rows
        ]

        return PaginatedResponse[GlobalSnapshotSummary](
            items=items,
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Category Service ========================


class CategoryService(BaseCRUDService[Category, CategoryCreate, CategoryUpdate, CategoryResponse]):
    model = Category
    audit_module = "finance"
    audit_entity_type = "categories"
    event_types = {
        "created": FinanceEvents.CATEGORY_CREATED,
        "updated": FinanceEvents.CATEGORY_UPDATED,
        "deleted": FinanceEvents.CATEGORY_DELETED,
    }

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

    @cached("finance", "list_categories", ttl=3600, key_params=("space_id",))
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

        # Collect tags for the payload (loaded synchronously after create+flush)
        _tags = (
            [t.tag for t in instance.tags] if "tags" in instance.__dict__ and instance.tags else []
        )
        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSACTION_CREATED,
                data={
                    "transaction_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                    "type": instance.type,
                    "amount": str(instance.amount),
                    "currency": instance.currency,
                    "description": instance.description,
                    "merchant": instance.merchant,
                    "payment_method": instance.payment_method,
                    "tags": _tags,
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
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

        _tags_upd = (
            [t.tag for t in instance.tags] if "tags" in instance.__dict__ and instance.tags else []
        )
        await event_bus.publish(
            Event(
                type=FinanceEvents.TRANSACTION_UPDATED,
                data={
                    "transaction_id": entity_id,
                    "id": entity_id,
                    "space_id": instance.space_id,
                    "type": instance.type,
                    "amount": str(instance.amount),
                    "currency": instance.currency,
                    "description": instance.description,
                    "merchant": instance.merchant,
                    "payment_method": instance.payment_method,
                    "tags": _tags_upd,
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
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
                data={
                    "transaction_id": txn_id,
                    "id": txn_id,
                    "space_id": instance.space_id,
                },
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
    event_types = {"created": FinanceEvents.INSTALLMENT_CREATED}
    event_id_alias = "plan_id"
    event_fields = ("num_installments",)

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
        if ym_set:
            spending_q = (
                select(
                    func.to_char(Transaction.transacted_at, "YYYY-MM").label("ym"),
                    Transaction.category_id,
                    func.coalesce(Category.name, "未分類").label("cat_name"),
                    func.sum(Transaction.amount).label("total"),
                )
                .outerjoin(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.space_id == space_id,
                    Transaction.type == "expense",
                    Transaction.status == "completed",
                    func.to_char(Transaction.transacted_at, "YYYY-MM").in_(list(ym_set)),
                )
                .group_by(
                    func.to_char(Transaction.transacted_at, "YYYY-MM"),
                    Transaction.category_id,
                    Category.name,
                )
            )
            spending_q = apply_privacy_filter(spending_q, Transaction, user_id)
            spending_rows = (await db.execute(spending_q)).all()
            for sr in spending_rows:
                spending_map[(sr.ym, sr.category_id)] = sr.total or Decimal("0")
                if sr.category_id:
                    cat_name_map[sr.category_id] = sr.cat_name

            # Total spending per month for budgets without category
            month_totals: dict[str, Decimal] = {}
            for sr in spending_rows:
                amt = sr.total or Decimal("0")
                month_totals[sr.ym] = month_totals.get(sr.ym, Decimal("0")) + amt
            for ym in ym_set:
                spending_map[(ym, None)] = month_totals.get(ym, Decimal("0"))

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

        # Batch: single query for all wallets instead of N queries
        wallet_ids = [w.id for w in wallets]
        change_q = (
            select(
                Transaction.wallet_id,
                Transaction.type,
                func.coalesce(func.sum(Transaction.amount), Decimal("0")).label("total"),
            )
            .where(
                Transaction.wallet_id.in_(wallet_ids),
                Transaction.status == "completed",
                func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
            )
            .group_by(Transaction.wallet_id, Transaction.type)
        )
        change_rows = (await db.execute(change_q)).all()

        # In-memory grouping
        changes: dict[str, Decimal] = {wid: Decimal("0") for wid in wallet_ids}
        for cr in change_rows:
            if cr.type == "income":
                changes[cr.wallet_id] += cr.total or Decimal("0")
            elif cr.type in ("expense", "transfer"):
                changes[cr.wallet_id] -= cr.total or Decimal("0")

        wallet_overview = [
            WalletOverviewItem(
                wallet_id=w.id,
                wallet_name=w.name,
                wallet_type=w.type,
                current_balance=w.current_balance,
                change=changes[w.id],
            )
            for w in wallets
        ]

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
        """Return income/expense/net for the last N months (single query)."""
        from datetime import date as _date
        from datetime import timedelta

        # Build year_month list
        today = _date.today()
        year_months: list[str] = []
        d = today.replace(day=1)
        for _ in range(months):
            year_months.append(d.strftime("%Y-%m"))
            d = (d - timedelta(days=1)).replace(day=1)
        year_months.reverse()  # chronological order

        # Single query: GROUP BY year_month, type
        ym_col = func.to_char(Transaction.transacted_at, "YYYY-MM").label("ym")
        totals_q = (
            select(
                ym_col,
                Transaction.type,
                func.coalesce(func.sum(Transaction.amount), Decimal("0")).label("total"),
            )
            .where(
                Transaction.space_id == space_id,
                Transaction.status == "completed",
                func.to_char(Transaction.transacted_at, "YYYY-MM").in_(year_months),
            )
            .group_by(ym_col, Transaction.type)
        )
        totals_q = apply_privacy_filter(totals_q, Transaction, user_id)
        rows = (await db.execute(totals_q)).all()

        # In-memory grouping
        data: dict[str, dict[str, Decimal]] = {ym: {} for ym in year_months}
        for row in rows:
            data[row.ym][row.type] = row.total or Decimal("0")

        return [
            MonthlyTrendResponse(
                year_month=ym,
                income=d.get("income", Decimal("0")),
                expense=d.get("expense", Decimal("0")),
                net=d.get("income", Decimal("0")) - d.get("expense", Decimal("0")),
            )
            for ym, d in ((ym, data[ym]) for ym in year_months)
        ]

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
