"""Finance routes — REST API endpoints.

Prefix: /api/finance (mounted in main.py)
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

ICON_DIR = Path(__file__).resolve().parents[4] / "data" / "finance-icons"
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
MAX_ICON_SIZE = 2 * 1024 * 1024  # 2 MB

from .schemas import (
    BudgetCreate,
    BudgetResponse,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    ExchangeRateResponse,
    FinanceSearchResult,
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
    TagStylesResponse,
    TagStylesUpdate,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
    TransferRequest,
    WalletCreate,
    WalletResponse,
    WalletSnapshotResponse,
    WalletSyncRequest,
    WalletUpdate,
)
from .services import (
    budget_service,
    category_service,
    installment_plan_service,
    subscription_service,
    summary_service,
    transaction_service,
    transfer_service,
    wallet_service,
)

router = APIRouter(tags=["finance"])


# ======================== Search ========================


VALID_ENTITY_TYPES = {"transaction", "subscription"}


@router.get("/search", response_model=list[FinanceSearchResult])
async def search_finance(
    q: str = Query(..., description="Search query string"),
    space_id: str = Query("default"),
    entity_type: str | None = Query(
        None, description="Filter by entity type: transaction or subscription"
    ),
    top_k: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    """Search finance records using Qdrant hybrid search with ILIKE fallback."""
    import logging

    from sqlalchemy import or_, select

    from src.shared.fallback_search import build_ilike_conditions
    from src.shared.qdrant_search import search_with_fallback

    from .models import Subscription, Transaction

    logger = logging.getLogger(__name__)

    if entity_type is not None and entity_type not in VALID_ENTITY_TYPES:
        raise BadRequestError(
            f"Invalid entity_type '{entity_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_ENTITY_TYPES))}",
            code="finance.invalid_entity_type",
        )

    # --- Qdrant path ---
    results, _meta = await search_with_fallback(
        q, space_id, "finance", top_k=top_k, entity_type_filter=entity_type
    )

    if results:
        return [
            FinanceSearchResult(
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                score=r.score,
                content_preview=r.content_preview,
                metadata=r.metadata,
            )
            for r in results
        ]

    logger.debug(
        "Qdrant returned 0 results for finance space=%s query=%r — falling back to ILIKE",
        space_id,
        q,
    )

    # --- ILIKE fallback ---
    out: list[FinanceSearchResult] = []

    if entity_type is None or entity_type == "transaction":
        txn_conditions = build_ilike_conditions(q, Transaction.description)
        txn_filter = (
            or_(*txn_conditions) if txn_conditions else Transaction.description.ilike(f"%{q}%")
        )
        txn_stmt = (
            select(Transaction)
            .where(
                Transaction.space_id == space_id,
                Transaction.deleted_at.is_(None),
                txn_filter,
            )
            .order_by(Transaction.updated_at.desc())
            .limit(top_k)
        )
        txn_rows = (await db.execute(txn_stmt)).scalars().all()
        for t in txn_rows:
            out.append(
                FinanceSearchResult(
                    entity_type="transaction",
                    entity_id=t.id,
                    score=1.0,
                    content_preview=(t.description or "")[:200],
                    metadata={
                        "amount": str(t.amount),
                        "type": t.type,
                        "wallet_id": t.wallet_id,
                    },
                )
            )

    if entity_type is None or entity_type == "subscription":
        sub_conditions = build_ilike_conditions(q, Subscription.name, Subscription.notes)
        sub_filter = (
            or_(*sub_conditions)
            if sub_conditions
            else or_(
                Subscription.name.ilike(f"%{q}%"),
                Subscription.notes.ilike(f"%{q}%"),
            )
        )
        sub_stmt = (
            select(Subscription)
            .where(
                Subscription.space_id == space_id,
                Subscription.deleted_at.is_(None),
                sub_filter,
            )
            .order_by(Subscription.updated_at.desc())
            .limit(top_k)
        )
        sub_rows = (await db.execute(sub_stmt)).scalars().all()
        for s in sub_rows:
            preview = s.name
            if s.notes:
                preview = f"{s.name} — {s.notes}"
            out.append(
                FinanceSearchResult(
                    entity_type="subscription",
                    entity_id=s.id,
                    score=1.0,
                    content_preview=preview[:200],
                    metadata={
                        "amount": str(s.amount),
                        "billing_cycle": s.billing_cycle,
                        "provider": s.name,
                    },
                )
            )

    # Sort combined results by score desc, then trim to top_k
    out.sort(key=lambda r: r.score, reverse=True)

    # Cross-encoder reranking
    from src.shared.rerank_utils import rerank_generic

    if len(out) > 1:
        out = await rerank_generic(
            query=q,
            results=out,
            content_fn=lambda r: r.content_preview,
            score_fn=lambda r: r.score,
            set_score_fn=lambda r, s: setattr(r, "score", s),
        )

    return out[:top_k]


# ======================== Wallets ========================


@router.get("/wallets", response_model=PaginatedResponse[WalletResponse])
async def list_wallets(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        include_inactive=include_inactive,
    )


@router.get("/wallets/net-worth", response_model=list[NetWorthPointResponse])
async def get_net_worth(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await summary_service.net_worth(db, space_id, user_id=user.get("id"))


@router.post("/wallets/global-snapshot", response_model=GlobalSnapshotResponse)
async def create_global_snapshot(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    result = await wallet_service.create_global_snapshot(db, space_id, user_id=user.get("id"))
    await db.commit()
    return result


@router.get("/wallets/global-snapshots", response_model=PaginatedResponse[GlobalSnapshotSummary])
async def list_global_snapshots(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.list_global_snapshots(
        db, space_id, PaginationParams(page=page, page_size=page_size)
    )


@router.get("/wallets/{wallet_id}", response_model=WalletResponse)
async def get_wallet(
    wallet_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await wallet_service.get_in_space(db, wallet_id, space_id)
    if not instance:
        raise NotFoundError("Wallet not found", code="finance.wallet_not_found")
    return wallet_service.to_response(instance)


@router.post("/wallets", response_model=WalletResponse, status_code=201)
async def create_wallet(
    data: WalletCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await wallet_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return wallet_service.to_response(instance)


@router.put("/wallets/{wallet_id}", response_model=WalletResponse)
async def update_wallet(
    wallet_id: str,
    data: WalletUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await wallet_service.update(
        db, wallet_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Wallet not found", code="finance.wallet_not_found")
    await db.commit()
    return wallet_service.to_response(instance)


@router.delete("/wallets/{wallet_id}", status_code=204)
async def delete_wallet(
    wallet_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await wallet_service.delete(db, wallet_id, user_id=user.get("id"), space_id=space_id):
        raise NotFoundError("Wallet not found", code="finance.wallet_not_found")
    await db.commit()


@router.post("/wallets/{wallet_id}/sync", response_model=WalletSnapshotResponse)
async def sync_wallet(
    wallet_id: str,
    data: WalletSyncRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    result = await wallet_service.sync(db, wallet_id, data, space_id, user_id=user.get("id"))
    await db.commit()
    return result


@router.get("/wallets/{wallet_id}/reconcile", response_model=ReconcileResponse)
async def reconcile_wallet(
    wallet_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.reconcile(db, wallet_id, user_id=user.get("id"))


@router.get(
    "/wallets/{wallet_id}/snapshots", response_model=PaginatedResponse[WalletSnapshotResponse]
)
async def list_wallet_snapshots(
    wallet_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.list_snapshots(
        db, wallet_id, PaginationParams(page=page, page_size=page_size)
    )


@router.get("/wallets/{wallet_id}/snapshots/diff", response_model=SnapshotDiffResponse)
async def diff_wallet_snapshots(
    wallet_id: str,
    from_v: int = Query(..., description="From version number"),
    to_v: int = Query(..., description="To version number"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.diff_snapshots(db, wallet_id, from_v, to_v)


@router.get("/wallets/{wallet_id}/snapshots/gap-analysis", response_model=GapAnalysisResponse)
async def gap_analysis(
    wallet_id: str,
    from_v: int = Query(..., description="From version number"),
    to_v: int = Query(..., description="To version number"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await wallet_service.gap_analysis(db, wallet_id, from_v, to_v)


# ======================== Categories ========================


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    space_id: str = Query("default"),
    flat: bool = Query(False, description="Return flat list instead of tree"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    if flat:
        result = await category_service.list(
            db,
            space_id,
            PaginationParams(page=page, page_size=page_size),
            user_id=user.get("id"),
        )
        return result.items
    return await category_service.list_tree(db, space_id, user_id=user.get("id"))


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    data: CategoryCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await category_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return category_service.to_response(instance)


@router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    data: CategoryUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await category_service.update(
        db, category_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Category not found", code="finance.category_not_found")
    await db.commit()
    return category_service.to_response(instance)


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await category_service.delete(
        db, category_id, user_id=user.get("id"), space_id=space_id
    ):
        raise NotFoundError("Category not found", code="finance.category_not_found")
    await db.commit()


# ======================== Transactions ========================


@router.get("/transactions", response_model=PaginatedResponse[TransactionResponse])
async def list_transactions(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    year_month: str | None = Query(None, description="Filter by YYYY-MM"),
    type: str | None = Query(None, description="income/expense/transfer"),
    category_id: str | None = Query(None),
    wallet_id: str | None = Query(None),
    tag: str | None = Query(None),
    search: str | None = Query(None, description="Full-text search on description/merchant"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await transaction_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        year_month=year_month,
        txn_type=type,
        category_id=category_id,
        wallet_id=wallet_id,
        tag=tag,
        search=search,
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await transaction_service.get_in_space(db, transaction_id, space_id)
    if not instance:
        raise NotFoundError("Transaction not found", code="finance.transaction_not_found")
    return transaction_service.to_response(instance)


@router.post("/transactions", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    data: TransactionCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await transaction_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return transaction_service.to_response(instance)


@router.put("/transactions/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: str,
    data: TransactionUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await transaction_service.update(
        db, transaction_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Transaction not found", code="finance.transaction_not_found")
    await db.commit()
    return transaction_service.to_response(instance)


@router.delete("/transactions/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await transaction_service.delete(
        db, transaction_id, user_id=user.get("id"), space_id=space_id
    ):
        raise NotFoundError("Transaction not found", code="finance.transaction_not_found")
    await db.commit()


# ======================== Trash (Soft Delete) ========================


@router.get("/trash/{entity_type}", response_model=PaginatedResponse)
async def list_trash(
    entity_type: str,
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    """List soft-deleted items for an entity type."""
    svc_map = {
        "transactions": transaction_service,
        "categories": category_service,
        "wallets": wallet_service,
        "subscriptions": subscription_service,
        "installment-plans": installment_plan_service,
        "budgets": budget_service,
    }
    svc = svc_map.get(entity_type)
    if not svc:
        raise NotFoundError(f"Unknown entity type: {entity_type}", code="finance.unknown_entity")
    return await svc.list_deleted(db, space_id, PaginationParams(page=page, page_size=page_size))


@router.post("/trash/{entity_type}/{entity_id}/restore", status_code=200)
async def restore_from_trash(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    """Restore a soft-deleted item."""
    svc_map = {
        "transactions": transaction_service,
        "categories": category_service,
        "wallets": wallet_service,
        "subscriptions": subscription_service,
        "installment-plans": installment_plan_service,
        "budgets": budget_service,
    }
    svc = svc_map.get(entity_type)
    if not svc:
        raise NotFoundError(f"Unknown entity type: {entity_type}", code="finance.unknown_entity")
    instance = await svc.restore(db, entity_id, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Item not found in trash", code="finance.not_in_trash")
    await db.commit()
    return svc.to_response(instance)


@router.delete("/trash/{entity_type}/{entity_id}", status_code=204)
async def purge_from_trash(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    """Permanently delete a soft-deleted item."""
    svc_map = {
        "transactions": transaction_service,
        "categories": category_service,
        "wallets": wallet_service,
        "subscriptions": subscription_service,
        "installment-plans": installment_plan_service,
        "budgets": budget_service,
    }
    svc = svc_map.get(entity_type)
    if not svc:
        raise NotFoundError(f"Unknown entity type: {entity_type}", code="finance.unknown_entity")
    if not await svc.purge(db, entity_id, user_id=user.get("id")):
        raise NotFoundError("Item not found", code="finance.not_found")
    await db.commit()


# ======================== Subscriptions ========================


@router.get("/subscriptions", response_model=PaginatedResponse[SubscriptionResponse])
async def list_subscriptions(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="active/paused/cancelled"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await subscription_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        status=status,
    )


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await subscription_service.get_in_space(db, subscription_id, space_id)
    if not instance:
        raise NotFoundError("Subscription not found", code="finance.subscription_not_found")
    return subscription_service.to_response(instance)


@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    data: SubscriptionCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await subscription_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return subscription_service.to_response(instance)


@router.put("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    data: SubscriptionUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await subscription_service.update(
        db, subscription_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Subscription not found", code="finance.subscription_not_found")
    await db.commit()
    return subscription_service.to_response(instance)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await subscription_service.delete(
        db, subscription_id, user_id=user.get("id"), space_id=space_id
    ):
        raise NotFoundError("Subscription not found", code="finance.subscription_not_found")
    await db.commit()


# ======================== Installment Plans ========================


@router.get("/installment-plans", response_model=PaginatedResponse[InstallmentPlanResponse])
async def list_installment_plans(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="active/completed/cancelled"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await installment_plan_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        status=status,
    )


@router.get("/installment-plans/{plan_id}", response_model=InstallmentPlanResponse)
async def get_installment_plan(
    plan_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await installment_plan_service.get_in_space(db, plan_id, space_id)
    if not instance:
        raise NotFoundError("Installment plan not found", code="finance.plan_not_found")
    return installment_plan_service.to_response(instance)


@router.post("/installment-plans", response_model=InstallmentPlanResponse, status_code=201)
async def create_installment_plan(
    data: InstallmentPlanCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await installment_plan_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return installment_plan_service.to_response(instance)


@router.put("/installment-plans/{plan_id}", response_model=InstallmentPlanResponse)
async def update_installment_plan(
    plan_id: str,
    data: InstallmentPlanUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await installment_plan_service.update(
        db, plan_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Installment plan not found", code="finance.plan_not_found")
    await db.commit()
    return installment_plan_service.to_response(instance)


# ======================== Budgets ========================


@router.get("/budgets", response_model=PaginatedResponse[BudgetResponse])
async def list_budgets(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    year_month: str | None = Query(None, description="Filter by YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await budget_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        year_month=year_month,
    )


@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def upsert_budget(
    data: BudgetCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await budget_service.upsert(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return budget_service.to_response(instance)


@router.get("/budgets/{year_month}/status")
async def get_budget_status(
    year_month: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await budget_service.get_status(db, space_id, year_month, user_id=user.get("id"))


# ======================== Transfer ========================


@router.post("/transfer", response_model=list[TransactionResponse])
async def execute_transfer(
    data: TransferRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    out_txn, in_txn = await transfer_service.transfer(
        db,
        space_id=space_id,
        from_wallet_id=data.from_wallet_id,
        to_wallet_id=data.to_wallet_id,
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        payment_method=data.payment_method,
        payment_detail=data.payment_detail,
        fee=data.fee,
        transacted_at=data.transacted_at,
        user_id=user.get("id"),
    )
    await db.commit()
    return [transaction_service.to_response(out_txn), transaction_service.to_response(in_txn)]


# ======================== Exchange Rates ========================


@router.get("/exchange-rates", response_model=ExchangeRateResponse)
async def get_exchange_rates_endpoint(
    user: dict = require_permission("finance.read"),
):
    from .exchange import get_exchange_rates

    return await get_exchange_rates()


# ======================== Summary ========================


@router.get("/summary/{year_month}", response_model=MonthlySummaryResponse)
async def get_monthly_summary(
    year_month: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await summary_service.monthly_summary(db, space_id, year_month, user_id=user.get("id"))


@router.get("/insights", response_model=list[MonthlyTrendResponse])
async def get_monthly_trends(
    months: int = Query(6, ge=1, le=24),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await summary_service.monthly_trends(db, space_id, months, user_id=user.get("id"))


# ======================== Icon Upload ========================


@router.post("/upload-icon")
async def upload_icon(
    file: UploadFile,
    user: dict = require_permission("finance.write"),
):
    """Upload an image to use as icon for transactions/subscriptions/installments."""
    if file.content_type not in ALLOWED_TYPES:
        raise BadRequestError(
            f"Unsupported file type: {file.content_type}", code="finance.invalid_icon_type"
        )
    data = await file.read()
    if len(data) > MAX_ICON_SIZE:
        raise BadRequestError("Icon file too large (max 2MB)", code="finance.icon_too_large")

    import hashlib

    ext = Path(file.filename or "icon.png").suffix or ".png"
    name = hashlib.sha256(data).hexdigest()[:16] + ext
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    dest = ICON_DIR / name
    dest.write_bytes(data)

    return {"icon_url": f"/finance/icons/{name}"}


@router.get("/icons/{filename}")
async def serve_icon(filename: str):
    """Serve an uploaded icon file."""
    path = ICON_DIR / filename
    if not path.is_file() or not path.resolve().is_relative_to(ICON_DIR.resolve()):
        raise NotFoundError("Icon not found", code="finance.icon_not_found")
    return FileResponse(path)


# ======================== Billing Cron ========================


@router.post("/billing/process")
async def process_billing(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("admin.write"),
):
    """Run subscription + installment billing for due items."""
    from .cron import run_all_cron

    result = await run_all_cron(db, space_id)
    await db.commit()
    return result


@router.post("/snapshots/process-monthly")
async def process_monthly_snapshots(
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("admin.write"),
):
    from .cron import process_monthly_snapshot

    result = await process_monthly_snapshot(db)
    await db.commit()
    return result


# ======================== Tag Styles ========================


@router.get("/tag-styles", response_model=TagStylesResponse)
async def get_tag_styles(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    from .models import TagStyle

    result = await db.execute(TagStyle.__table__.select().where(TagStyle.space_id == space_id))
    row = result.first()
    return TagStylesResponse(styles=row.styles if row else {})


@router.put("/tag-styles", response_model=TagStylesResponse)
async def update_tag_styles(
    body: TagStylesUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from .models import TagStyle

    stmt = (
        pg_insert(TagStyle)
        .values(
            space_id=space_id,
            created_by=user.get("id"),
            styles=body.styles,
        )
        .on_conflict_do_update(
            index_elements=["space_id"],
            set_={"styles": body.styles},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return TagStylesResponse(styles=body.styles)
