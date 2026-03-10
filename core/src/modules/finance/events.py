"""Finance event handlers — subscribers for finance domain events."""

from decimal import Decimal

import structlog

from src.events.bus import Event, event_bus
from src.events.types import FinanceEvents, InvestEvents
from src.shared.cache import register_invalidation
from src.shared.database import async_session_factory

logger = structlog.get_logger()

# --- Cache invalidation wiring ---

register_invalidation(
    module="finance",
    operations=["list_categories"],
    events=[
        FinanceEvents.CATEGORY_CREATED,
        FinanceEvents.CATEGORY_UPDATED,
        FinanceEvents.CATEGORY_DELETED,
    ],
)

register_invalidation(
    module="finance",
    operations=["list_wallets"],
    events=[
        FinanceEvents.WALLET_CREATED,
        FinanceEvents.WALLET_UPDATED,
        FinanceEvents.WALLET_DELETED,
        FinanceEvents.WALLET_SYNCED,
    ],
)


@event_bus.on(InvestEvents.VALUATION_UPDATED)
async def on_invest_valuation_updated(event: Event) -> None:
    """When invest valuation updates, sync linked finance wallet balances.

    For each invest account with a finance_wallet_id, set the wallet's
    current_balance to the account's total market value.
    """
    space_id = event.data.get("space_id")
    if not space_id:
        return

    # Import here to avoid circular imports at module load time
    from src.modules.invest.services import account_service, position_service

    async with async_session_factory() as db:
        try:
            # Get all invest accounts for this space
            accounts_resp = await account_service.list(db, space_id)
            for acct in accounts_resp.items:
                if not acct.finance_wallet_id:
                    continue

                # Get positions for this account to compute market value
                positions_resp = await position_service.list(db, space_id, account_id=acct.id)
                total_mv = sum(
                    (p.market_value for p in positions_resp.items),
                    Decimal("0"),
                )

                # Update the linked finance wallet balance
                from src.modules.finance.models import Wallet

                wallet = await db.get(Wallet, acct.finance_wallet_id)
                if wallet and wallet.space_id == space_id:
                    wallet.current_balance = total_mv
                    logger.info(
                        "invest_wallet_synced",
                        wallet_id=acct.finance_wallet_id,
                        market_value=str(total_mv),
                    )

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("invest_valuation_sync_failed", space_id=space_id)
