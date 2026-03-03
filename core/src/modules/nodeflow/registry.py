"""Service registry — maps module.action to callable service methods.

The registry allows the nodeflow engine to dynamically invoke any
registered module service method by name, without direct imports.
"""

from collections.abc import Callable, Coroutine
from typing import Any

import structlog

logger = structlog.get_logger()

ActionHandler = Callable[..., Coroutine[Any, Any, Any]]

_registry: dict[str, ActionHandler] = {}


def register_action(module: str, action: str, handler: ActionHandler) -> None:
    key = f"{module}.{action}"
    _registry[key] = handler
    logger.debug("nodeflow_action_registered", key=key)


def get_action(module: str, action: str) -> ActionHandler | None:
    return _registry.get(f"{module}.{action}")


def list_actions() -> list[str]:
    return sorted(_registry.keys())


def register_module_actions() -> None:
    """Register known module service methods at startup.

    Called once during lifespan. Add new modules here as they gain
    nodeflow-compatible actions.
    """
    from src.modules.invest.services import (
        account_service,
        portfolio_service,
        position_service,
        trade_service,
    )

    # invest module
    register_action("invest", "list_accounts", account_service.list)
    register_action("invest", "get_account_summary", account_service.get_summary)
    register_action("invest", "list_positions", position_service.list)
    register_action("invest", "create_trade", trade_service.create)
    register_action("invest", "get_portfolio", portfolio_service.get_portfolio)
    register_action("invest", "refresh_quotes", portfolio_service.refresh_quotes)

    # finance module — add commonly useful actions
    from src.modules.finance.services import (
        budget_service,
        transaction_service,
        wallet_service,
    )

    register_action("finance", "create_transaction", transaction_service.create)
    register_action("finance", "list_transactions", transaction_service.list)
    register_action("finance", "list_wallets", wallet_service.list)
    register_action("finance", "get_budget_status", budget_service.list)

    logger.info("nodeflow_registry_initialized", action_count=len(_registry))
