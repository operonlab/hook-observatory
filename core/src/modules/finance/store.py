"""Finance FeatureStore — NgRx-style state container for the finance module.

Tracks hot/cache state for wallets, categories, and recent transactions.
Does NOT replicate DB logic — thin reactive layer on top of services.py.

Usage:
    from src.modules.finance.store import finance_store, select_wallets
    from src.modules.finance.store import TransactionCreated, WalletCreated

    # Dispatch (also publishes to EventBus)
    await finance_store.dispatch(WalletCreated(id="w1", name="Main", balance=1000))

    # Select
    wallets = finance_store.select(select_wallets)
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable, update_in
from src.shared.journal import ActionJournal
from src.shared.middleware import AuditMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect

logger = structlog.get_logger()

# ── 1. Actions ────────────────────────────────────────────────────────────

# Transaction
TransactionCreated = create_action("finance.transaction.created")
TransactionUpdated = create_action("finance.transaction.updated")
TransactionDeleted = create_action("finance.transaction.deleted")

# Budget
BudgetExceeded = create_action("finance.budget.exceeded")

# Category
CategoryCreated = create_action("finance.category.created")
CategoryUpdated = create_action("finance.category.updated")
CategoryDeleted = create_action("finance.category.deleted")

# Wallet
WalletCreated = create_action("finance.wallet.created")
WalletUpdated = create_action("finance.wallet.updated")
WalletDeleted = create_action("finance.wallet.deleted")
WalletSynced = create_action("finance.wallet.synced")
WalletReconciled = create_action("finance.wallet.reconciled")
WalletCashGap = create_action("finance.wallet.cash_gap_detected")

# Installment
InstallmentCreated = create_action("finance.installment.created")
InstallmentCompleted = create_action("finance.installment.completed")
InstallmentDue = create_action("finance.installment.due")
InstallmentCancelled = create_action("finance.installment.cancelled")

# Transfer
TransferCompleted = create_action("finance.transfer.completed")

# Subscription
SubscriptionRenewed = create_action("finance.subscription.renewed")

# Snapshot
GlobalSnapshotCreated = create_action("finance.snapshot.global_created")

# Privacy
PrivacyToggled = create_action("finance.privacy.toggled")

# FSM
StateTransitioned = create_action("finance.state.transitioned")

# Cross-module (invest)
InvestValuationUpdated = create_action("invest.valuation.updated")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_RECENT_TRANSACTIONS = 50


def _handle_transaction_created(state, action):
    """Prepend to recent_transactions list (capped at MAX_RECENT_TRANSACTIONS)."""
    payload = action.payload or {}
    tx_id = payload.get("id")
    if not tx_id:
        return state

    recent = state.get("recent_transactions", ())
    # Prepend new transaction, trim to cap
    new_recent = (to_immutable(payload), *recent)[:_MAX_RECENT_TRANSACTIONS]

    # Optionally update wallet balance if amount + wallet_id present
    wallet_id = payload.get("wallet_id")
    amount = payload.get("amount")
    tx_type = payload.get("type")  # "income" | "expense" | "transfer"

    if wallet_id and amount is not None:
        try:
            delta = Decimal(str(amount))
            # expenses are negative, incomes positive
            if tx_type == "expense":
                delta = -abs(delta)
            elif tx_type == "income":
                delta = abs(delta)
            else:
                delta = Decimal("0")  # transfer handled separately

            if delta != 0:
                state = update_in(
                    state,
                    ["wallets", wallet_id, "current_balance"],
                    lambda cur: Decimal(str(cur)) + delta if cur is not None else delta,
                )
        except Exception as exc:
            logger.warning("finance_reducer.transaction_balance_update_skipped", error=str(exc))

    return state.set("recent_transactions", new_recent)


def _handle_transaction_deleted(state, action):
    """Remove transaction from recent_transactions if present."""
    payload = action.payload or {}
    tx_id = payload.get("id")
    if not tx_id:
        return state

    recent = state.get("recent_transactions", ())
    new_recent = tuple(tx for tx in recent if tx.get("id") != tx_id)
    if len(new_recent) == len(recent):
        return state  # nothing removed, no change
    return state.set("recent_transactions", new_recent)


def _handle_wallet_upsert(state, action):
    """Insert or replace wallet in wallets map."""
    payload = action.payload or {}
    wallet_id = payload.get("id")
    if not wallet_id:
        return state
    return update_in(state, ["wallets", wallet_id], lambda _: to_immutable(payload))


def _handle_wallet_deleted(state, action):
    """Remove wallet from wallets map."""
    payload = action.payload or {}
    wallet_id = payload.get("id")
    if not wallet_id:
        return state
    wallets = state.get("wallets")
    if wallets is None or wallet_id not in wallets:
        return state
    return state.set("wallets", wallets.delete(wallet_id))


def _handle_wallet_synced(state, action):
    """Merge synced balance into existing wallet entry."""
    payload = action.payload or {}
    wallet_id = payload.get("id") or payload.get("wallet_id")
    current_balance = payload.get("current_balance")
    if not wallet_id or current_balance is None:
        return state
    return update_in(
        state,
        ["wallets", wallet_id, "current_balance"],
        lambda _: to_immutable(current_balance),
    )


def _handle_transfer_completed(state, action):
    """Update both source and destination wallet balances."""
    payload = action.payload or {}
    from_id = payload.get("from_wallet_id")
    to_id = payload.get("to_wallet_id")
    amount = payload.get("amount")
    if not (from_id and to_id and amount is not None):
        return state
    try:
        delta = abs(Decimal(str(amount)))
        state = update_in(
            state,
            ["wallets", from_id, "current_balance"],
            lambda cur: (Decimal(str(cur)) - delta) if cur is not None else -delta,
        )
        state = update_in(
            state,
            ["wallets", to_id, "current_balance"],
            lambda cur: (Decimal(str(cur)) + delta) if cur is not None else delta,
        )
    except Exception as exc:
        logger.warning("finance_reducer.transfer_balance_update_skipped", error=str(exc))
    return state


def _handle_category_upsert(state, action):
    payload = action.payload or {}
    cat_id = payload.get("id")
    if not cat_id:
        return state
    return update_in(state, ["categories", cat_id], lambda _: to_immutable(payload))


def _handle_category_deleted(state, action):
    payload = action.payload or {}
    cat_id = payload.get("id")
    if not cat_id:
        return state
    categories = state.get("categories")
    if categories is None or cat_id not in categories:
        return state
    return state.set("categories", categories.delete(cat_id))


def _handle_budget_exceeded(state, action):
    """Flag a budget-exceeded alert in state."""
    payload = action.payload or {}
    budget_id = payload.get("budget_id") or payload.get("id")
    if not budget_id:
        return state
    return update_in(
        state,
        ["budget_alerts", budget_id],
        lambda _: to_immutable({"exceeded": True, **payload}),
    )


finance_reducer = create_reducer(
    {
        "wallets": {},
        "categories": {},
        "recent_transactions": [],
        "budget_alerts": {},
    },
    # Transactions
    on(TransactionCreated, _handle_transaction_created),
    on(TransactionUpdated, lambda s, a: s),  # no hot-state change needed for updates
    on(TransactionDeleted, _handle_transaction_deleted),
    # Budget
    on(BudgetExceeded, _handle_budget_exceeded),
    # Categories
    on(CategoryCreated, _handle_category_upsert),
    on(CategoryUpdated, _handle_category_upsert),
    on(CategoryDeleted, _handle_category_deleted),
    # Wallets
    on(WalletCreated, _handle_wallet_upsert),
    on(WalletUpdated, _handle_wallet_upsert),
    on(WalletDeleted, _handle_wallet_deleted),
    on(WalletSynced, _handle_wallet_synced),
    on(WalletReconciled, _handle_wallet_synced),  # same shape — update balance
    on(WalletCashGap, lambda s, a: s),  # alerting only, no state mutation
    # Installments — no hot state
    on(InstallmentCreated, lambda s, a: s),
    on(InstallmentCompleted, lambda s, a: s),
    on(InstallmentDue, lambda s, a: s),
    on(InstallmentCancelled, lambda s, a: s),
    # Transfer
    on(TransferCompleted, _handle_transfer_completed),
    # Subscription / Snapshot / Privacy — no hot state
    on(SubscriptionRenewed, lambda s, a: s),
    on(GlobalSnapshotCreated, lambda s, a: s),
    on(PrivacyToggled, lambda s, a: s),
    # FSM
    on(StateTransitioned, lambda s, a: s),
)

# ── 3. Selectors ──────────────────────────────────────────────────────────

select_wallets = create_selector(lambda s: s["wallets"])
select_categories = create_selector(lambda s: s["categories"])
select_recent_transactions = create_selector(lambda s: s["recent_transactions"])
select_budget_alerts = create_selector(lambda s: s["budget_alerts"])


# Parameterised selectors — return a fresh selector per ID
def select_wallet_by_id(wallet_id: str):
    """Return a memoized selector that extracts a single wallet by ID."""
    return create_selector(lambda s: s["wallets"].get(wallet_id))


def select_category_by_id(category_id: str):
    """Return a memoized selector that extracts a single category by ID."""
    return create_selector(lambda s: s["categories"].get(category_id))


# Derived selectors
select_wallet_count = create_selector(
    select_wallets,
    result_fn=lambda wallets: len(wallets),
)

select_total_balance = create_selector(
    select_wallets,
    result_fn=lambda wallets: sum(
        (Decimal(str(w.get("current_balance", 0))) for w in wallets.values()),
        Decimal("0"),
    ),
)

# ── 4. Store Instance ─────────────────────────────────────────────────────

finance_store = FeatureStore(
    "finance",
    finance_reducer,
    journal=ActionJournal(checkpoint_interval=50),
    middlewares=[
        AuditMiddleware(
            audit_types={
                "finance.transaction.created",
                "finance.wallet.synced",
                "finance.transfer.completed",
                "finance.privacy.toggled",
            }
        ),
    ],
)

# ── 5. Effects ────────────────────────────────────────────────────────────


@effect(InvestValuationUpdated, store=finance_store)
async def sync_invest_wallet(action, store) -> None:
    """When invest valuation updates, sync linked finance wallet balances.

    Mirrors on_invest_valuation_updated logic from events.py but as a
    FeatureStore Effect — dispatches WalletSynced to update hot state
    after the DB write completes.
    """
    from decimal import Decimal

    from src.shared.database import async_session_factory

    payload = action.payload or {}
    space_id = payload.get("space_id") if isinstance(payload, dict) else None
    if not space_id:
        return

    # Import here to avoid circular imports at module load time
    from src.modules.invest.services import account_service, position_service

    async with async_session_factory() as db:
        try:
            accounts_resp = await account_service.list(db, space_id)
            for acct in accounts_resp.items:
                if not acct.finance_wallet_id:
                    continue

                positions_resp = await position_service.list(db, space_id, account_id=acct.id)
                total_mv = sum(
                    (p.market_value for p in positions_resp.items),
                    Decimal("0"),
                )

                from src.modules.finance.models import Wallet

                wallet = await db.get(Wallet, acct.finance_wallet_id)
                if wallet and wallet.space_id == space_id:
                    wallet.current_balance = total_mv
                    logger.info(
                        "invest_wallet_synced_via_store",
                        wallet_id=str(acct.finance_wallet_id),
                        market_value=str(total_mv),
                    )
                    # Reflect the balance update into the hot store state
                    store.dispatch_sync(
                        WalletSynced(
                            id=str(acct.finance_wallet_id),
                            current_balance=str(total_mv),
                            space_id=space_id,
                        )
                    )

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("invest_valuation_sync_via_store_failed", space_id=space_id)


@effect(StateTransitioned, store=finance_store)
async def publish_state_changed(action, store) -> None:
    """Publish state_changed event to EventBus (replaces emit_state_changed)."""
    payload = action.payload or {}
    module_name = payload.get("module", "finance")
    entity_type = payload.get("entity_type", "")
    event_type = f"{module_name}.{entity_type}.state_changed"
    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type=event_type,
                data={
                    "entity_id": payload.get("entity_id"),
                    "old_state": payload.get("old_state"),
                    "new_state": payload.get("new_state"),
                    **{
                        k: v
                        for k, v in payload.items()
                        if k
                        not in (
                            "module",
                            "entity_type",
                            "entity_id",
                            "old_state",
                            "new_state",
                            "user_id",
                        )
                    },
                },
                source=f"{module_name}.fsm",
                user_id=payload.get("user_id"),
            )
        )
    except Exception:
        logger.debug("EventBus publish failed for %s", event_type, exc_info=True)
