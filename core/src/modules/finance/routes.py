"""Finance routes — REST API endpoints.

Prefix: /api/finance (mounted in main.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    BudgetCreate,
    BudgetResponse,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    InstallmentPlanCreate,
    InstallmentPlanResponse,
    InstallmentPlanUpdate,
    MonthlySummaryResponse,
    ReconcileResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
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


@router.get("/wallets/{wallet_id}", response_model=WalletResponse)
async def get_wallet(
    wallet_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await wallet_service.get(db, wallet_id)
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await wallet_service.update(db, wallet_id, data)
    if not instance:
        raise NotFoundError("Wallet not found", code="finance.wallet_not_found")
    await db.commit()
    return wallet_service.to_response(instance)


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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await category_service.update(db, category_id, data)
    if not instance:
        raise NotFoundError("Category not found", code="finance.category_not_found")
    await db.commit()
    return category_service.to_response(instance)


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await category_service.delete(db, category_id):
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await transaction_service.get(db, transaction_id)
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await transaction_service.update(db, transaction_id, data)
    if not instance:
        raise NotFoundError("Transaction not found", code="finance.transaction_not_found")
    await db.commit()
    return transaction_service.to_response(instance)


@router.delete("/transactions/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    if not await transaction_service.delete(db, transaction_id):
        raise NotFoundError("Transaction not found", code="finance.transaction_not_found")
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await subscription_service.get(db, subscription_id)
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await subscription_service.update(db, subscription_id, data)
    if not instance:
        raise NotFoundError("Subscription not found", code="finance.subscription_not_found")
    await db.commit()
    return subscription_service.to_response(instance)


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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    instance = await installment_plan_service.get(db, plan_id)
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
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.write"),
):
    instance = await installment_plan_service.update(db, plan_id, data)
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


# ======================== Summary ========================


@router.get("/summary/{year_month}", response_model=MonthlySummaryResponse)
async def get_monthly_summary(
    year_month: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("finance.read"),
):
    return await summary_service.monthly_summary(db, space_id, year_month, user_id=user.get("id"))
