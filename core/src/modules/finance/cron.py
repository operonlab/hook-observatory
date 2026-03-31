"""Finance cron jobs — installment due processing and subscription billing.

All functions are idempotent and safe to re-run. They operate on status fields
as guards and use invoice_number for deduplication.

Caller is responsible for managing the DB transaction (commit/rollback).
These functions call ``db.flush()`` but never ``db.commit()``.
"""

from datetime import UTC, date, datetime

import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from src.events.bus import Event, event_bus
from src.events.types import FinanceEvents

from .models import InstallmentPlan, Subscription, Transaction, Wallet
from .services import _adjust_wallet_balance, wallet_service

logger = structlog.get_logger()


async def process_installment_due(db: AsyncSession, space_id: str) -> int:
    """Process all installment transactions that are due for a given space.

    Finds transactions where:
    - space_id = space_id
    - status = 'scheduled'
    - transacted_at <= now()
    - installment_plan_id IS NOT NULL
    - deleted_at IS NULL

    For each due transaction:
    1. Update status to 'completed'
    2. Apply wallet balance delta (expense deduction)
    3. Fire INSTALLMENT_DUE event

    After processing all due transactions, check if any InstallmentPlan
    has all its transactions completed and mark those plans as 'completed'.

    This function is idempotent: it only operates on status='scheduled' rows.
    Re-running will not process already-completed transactions.

    Args:
        db: Async database session. Caller manages commit/rollback.
        space_id: The space to process installments for.

    Returns:
        Count of processed (newly completed) transactions.
    """
    now = datetime.now(UTC)

    # Find all due installment transactions (exclude deleted, scope to space)
    due_q = select(Transaction).where(
        Transaction.space_id == space_id,
        Transaction.status == "scheduled",
        Transaction.transacted_at <= now,
        Transaction.installment_plan_id != None,  # noqa: E711
        Transaction.deleted_at.is_(None),
    ).with_for_update(skip_locked=True)
    due_txns = (await db.execute(due_q)).scalars().all()

    if not due_txns:
        logger.info("installment_due_check", processed=0, message="no due transactions")
        return 0

    processed = 0
    affected_plan_ids: set[str] = set()

    for txn in due_txns:
        # Mark as completed
        txn.status = "completed"

        # Apply wallet balance delta (installments are expenses)
        delta = -txn.amount
        await _adjust_wallet_balance(db, txn.wallet_id, delta)

        # Deduct fee if present
        if txn.fee is not None and txn.fee != 0:
            await _adjust_wallet_balance(db, txn.wallet_id, -txn.fee)

        affected_plan_ids.add(txn.installment_plan_id)
        processed += 1

        await event_bus.publish(
            Event(
                type=FinanceEvents.INSTALLMENT_DUE,
                data={
                    "transaction_id": txn.id,
                    "installment_plan_id": txn.installment_plan_id,
                    "installment_number": txn.installment_number,
                    "amount": str(txn.amount),
                },
                source="finance.cron",
                user_id=txn.created_by,
            )
        )

    await db.flush()

    # Check if any affected plans are now fully completed
    for plan_id in affected_plan_ids:
        plan = await db.get(InstallmentPlan, plan_id)
        if not plan or plan.status != "active":
            continue

        # Count remaining scheduled transactions for this plan (exclude deleted)
        remaining_q = select(func.count()).where(
            Transaction.installment_plan_id == plan_id,
            Transaction.status == "scheduled",
            Transaction.deleted_at.is_(None),
        )
        remaining = (await db.execute(remaining_q)).scalar_one()

        if remaining == 0:
            plan.status = "completed"
            await db.flush()

            await event_bus.publish(
                Event(
                    type=FinanceEvents.INSTALLMENT_COMPLETED,
                    data={
                        "plan_id": plan_id,
                        "description": plan.description,
                        "total_amount": str(plan.total_amount),
                        "num_installments": plan.num_installments,
                    },
                    source="finance.cron",
                    user_id=plan.created_by,
                )
            )

            logger.info(
                "installment_plan_completed",
                plan_id=plan_id,
                description=plan.description,
            )

    logger.info(
        "installment_due_processed",
        processed=processed,
        affected_plans=len(affected_plan_ids),
    )

    return processed


def _next_billing_date(current: date, billing_cycle: str) -> date:
    """Calculate the next billing date based on the cycle.

    Args:
        current: The current billing date.
        billing_cycle: One of 'monthly', 'yearly', 'weekly'.

    Returns:
        The next billing date.
    """
    if billing_cycle == "monthly":
        return current + relativedelta(months=1)
    elif billing_cycle == "yearly":
        return current + relativedelta(years=1)
    elif billing_cycle == "weekly":
        return current + relativedelta(weeks=1)
    else:
        # Fallback: treat unknown cycles as monthly
        logger.warning("unknown_billing_cycle", cycle=billing_cycle, fallback="monthly")
        return current + relativedelta(months=1)


async def process_subscription_billing(db: AsyncSession, space_id: str) -> int:
    """Process subscription renewals that are due for billing.

    Finds active subscriptions where next_billing <= today.

    For each due subscription:
    1. Check idempotency via invoice_number = 'sub:{sub_id}:{billing_period}'
    2. If no existing transaction, create a new expense transaction
    3. Update wallet balance
    4. Advance next_billing to the next period
    5. Fire SUBSCRIPTION_RENEWED event

    This function is idempotent: duplicate billing for the same period is
    prevented by the invoice_number check.

    Args:
        db: Async database session. Caller manages commit/rollback.
        space_id: The space to process subscriptions for.

    Returns:
        Count of processed (newly billed) subscriptions.
    """
    today = date.today()

    subs_q = select(Subscription).where(
        Subscription.space_id == space_id,
        Subscription.status == "active",
        Subscription.next_billing != None,  # noqa: E711
        Subscription.next_billing <= today,
        Subscription.deleted_at.is_(None),
    ).with_for_update(skip_locked=True)
    subs = (await db.execute(subs_q)).scalars().all()

    if not subs:
        logger.info(
            "subscription_billing_check",
            space_id=space_id,
            processed=0,
            message="no due subscriptions",
        )
        return 0

    processed = 0

    for sub in subs:
        # Catch-up loop: process ALL missed billing periods, not just one.
        # If the cron job was down for days, this ensures every period is billed.
        while sub.next_billing <= today:
            billing_period = sub.next_billing.isoformat()
            invoice_number = f"sub:{sub.id}:{billing_period}"

            # Idempotency check: skip if transaction already exists for this period
            existing_q = select(func.count()).where(
                Transaction.invoice_number == invoice_number,
            )
            existing_count = (await db.execute(existing_q)).scalar_one()

            if existing_count > 0:
                logger.debug(
                    "subscription_billing_skipped",
                    subscription_id=sub.id,
                    billing_period=billing_period,
                    reason="already_billed",
                )
                # Still advance next_billing to avoid re-checking
                sub.next_billing = _next_billing_date(sub.next_billing, sub.billing_cycle)
                await db.flush()
                continue

            # Create billing transaction
            txn_id = uuid7().hex
            now = datetime.now(UTC)
            txn = Transaction(
                id=txn_id,
                space_id=space_id,
                created_by=sub.created_by,
                type="expense",
                amount=sub.amount,
                currency=sub.currency,
                description=f"Subscription: {sub.name}",
                payment_method=sub.payment_method or "auto",
                payment_detail=sub.payment_detail,
                category_id=sub.category_id,
                wallet_id=sub.wallet_id,
                status="completed",
                invoice_number=invoice_number,
                transacted_at=now,
            )
            db.add(txn)

            # Update wallet balance (expense = negative delta)
            if sub.wallet_id:
                await _adjust_wallet_balance(db, sub.wallet_id, -sub.amount)

            # Advance to next billing period
            old_next = sub.next_billing
            sub.next_billing = _next_billing_date(sub.next_billing, sub.billing_cycle)

            await db.flush()
            processed += 1

            await event_bus.publish(
                Event(
                    type=FinanceEvents.SUBSCRIPTION_RENEWED,
                    data={
                        "subscription_id": sub.id,
                        "transaction_id": txn_id,
                        "name": sub.name,
                        "amount": str(sub.amount),
                        "billing_period": billing_period,
                        "next_billing": sub.next_billing.isoformat(),
                    },
                    source="finance.cron",
                    user_id=sub.created_by,
                )
            )

            logger.info(
                "subscription_billed",
                subscription_id=sub.id,
                name=sub.name,
                amount=str(sub.amount),
                billing_period=billing_period,
                old_next_billing=old_next.isoformat(),
                new_next_billing=sub.next_billing.isoformat(),
            )

    logger.info(
        "subscription_billing_processed",
        space_id=space_id,
        processed=processed,
        total_checked=len(subs),
    )

    return processed


async def run_all_cron(db: AsyncSession, space_id: str) -> dict:
    """Run all finance cron jobs and return a summary.

    Convenience function that executes both installment due processing
    and subscription billing in sequence.

    Args:
        db: Async database session. Caller manages commit/rollback.
        space_id: The space to process subscriptions for.
            (Installment processing is cross-space by design.)

    Returns:
        Summary dict with counts and timestamp.
    """
    logger.info("finance_cron_start", space_id=space_id)

    installments_processed = await process_installment_due(db, space_id)
    subscriptions_processed = await process_subscription_billing(db, space_id)

    summary = {
        "executed_at": datetime.now(UTC).isoformat(),
        "space_id": space_id,
        "installments_processed": installments_processed,
        "subscriptions_processed": subscriptions_processed,
        "total_processed": installments_processed + subscriptions_processed,
    }

    logger.info("finance_cron_complete", **summary)

    return summary


async def process_monthly_snapshot(db: AsyncSession) -> dict:
    """Create global snapshots for all active spaces."""
    from sqlalchemy import distinct

    # Get all distinct space_ids with active wallets
    space_ids = (await db.execute(
        select(distinct(Wallet.space_id)).where(
            Wallet.is_active == True,  # noqa: E712
            Wallet.deleted_at == None,  # noqa: E711
        )
    )).scalars().all()

    results = []
    for space_id in space_ids:
        result = await wallet_service.create_global_snapshot(db, space_id)
        results.append({"space_id": space_id, "batch_id": result.batch_id})

    return {"spaces_processed": len(results), "results": results}
