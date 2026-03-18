"""Finance API client — Core module at /api/finance.

Wraps transactions, wallets, budgets, subscriptions, installments,
categories, transfers, and analytics endpoints.

Usage:
    from workshop.clients.finance import FinanceClient

    client = FinanceClient()
    wallets = client.list_wallets()
    txns = client.list_transactions(wallet_id="xxx", year_month="2026-03")
"""

from typing import Any

from ._base import APIError, BaseClient

FinanceError = APIError


class FinanceClient(BaseClient):
    """HTTP client for the Finance Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="finance", **kwargs)

    # ======================== Wallets ========================

    def list_wallets(
        self, include_inactive: bool = False, page: int = 1, page_size: int = 20
    ) -> dict:
        """List wallets. GET /wallets"""
        return self._get(
            "/wallets", {"include_inactive": include_inactive, "page": page, "page_size": page_size}
        )

    def get_wallet(self, wallet_id: str) -> dict:
        """Get wallet by ID. GET /wallets/{id}"""
        return self._get(f"/wallets/{wallet_id}")

    def create_wallet(self, data: dict) -> dict:
        """Create a wallet. POST /wallets"""
        return self._post("/wallets", data)

    def update_wallet(self, wallet_id: str, data: dict) -> dict:
        """Update a wallet. PUT /wallets/{id}"""
        return self._put(f"/wallets/{wallet_id}", data)

    def sync_wallet(self, wallet_id: str, data: dict) -> dict:
        """Sync wallet balance (reconciliation). POST /wallets/{id}/sync"""
        return self._post(f"/wallets/{wallet_id}/sync", data)

    def reconcile_wallet(self, wallet_id: str) -> dict:
        """Get reconciliation data. GET /wallets/{id}/reconcile"""
        return self._get(f"/wallets/{wallet_id}/reconcile")

    def get_net_worth(self) -> list[dict]:
        """Get net worth history. GET /wallets/net-worth"""
        return self._get("/wallets/net-worth")

    # ======================== Categories ========================

    def list_categories(
        self, flat: bool = False, page: int = 1, page_size: int = 100
    ) -> list[dict]:
        """List categories (tree or flat). GET /categories"""
        return self._get("/categories", {"flat": flat, "page": page, "page_size": page_size})

    def create_category(self, data: dict) -> dict:
        """Create a category. POST /categories"""
        return self._post("/categories", data)

    def update_category(self, category_id: str, data: dict) -> dict:
        """Update a category. PUT /categories/{id}"""
        return self._put(f"/categories/{category_id}", data)

    def delete_category(self, category_id: str) -> None:
        """Delete a category. DELETE /categories/{id}"""
        self._delete(f"/categories/{category_id}")

    # ======================== Transactions ========================

    def list_transactions(
        self,
        year_month: str | None = None,
        type: str | None = None,
        category_id: str | None = None,
        wallet_id: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List transactions with filters. GET /transactions"""
        return self._get(
            "/transactions",
            {
                "year_month": year_month,
                "type": type,
                "category_id": category_id,
                "wallet_id": wallet_id,
                "tag": tag,
                "search": search,
                "page": page,
                "page_size": page_size,
            },
        )

    def get_transaction(self, transaction_id: str) -> dict:
        """Get transaction by ID. GET /transactions/{id}"""
        return self._get(f"/transactions/{transaction_id}")

    def create_transaction(self, data: dict) -> dict:
        """Create a transaction. POST /transactions"""
        return self._post("/transactions", data)

    def update_transaction(self, transaction_id: str, data: dict) -> dict:
        """Update a transaction. PUT /transactions/{id}"""
        return self._put(f"/transactions/{transaction_id}", data)

    def delete_transaction(self, transaction_id: str) -> None:
        """Delete a transaction. DELETE /transactions/{id}"""
        self._delete(f"/transactions/{transaction_id}")

    # ======================== Subscriptions ========================

    def list_subscriptions(
        self, status: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict:
        """List subscriptions. GET /subscriptions"""
        return self._get("/subscriptions", {"status": status, "page": page, "page_size": page_size})

    def get_subscription(self, subscription_id: str) -> dict:
        """Get subscription by ID. GET /subscriptions/{id}"""
        return self._get(f"/subscriptions/{subscription_id}")

    def create_subscription(self, data: dict) -> dict:
        """Create a subscription. POST /subscriptions"""
        return self._post("/subscriptions", data)

    def update_subscription(self, subscription_id: str, data: dict) -> dict:
        """Update a subscription. PUT /subscriptions/{id}"""
        return self._put(f"/subscriptions/{subscription_id}", data)

    # ======================== Installment Plans ========================

    def list_installments(
        self, status: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict:
        """List installment plans. GET /installment-plans"""
        return self._get(
            "/installment-plans", {"status": status, "page": page, "page_size": page_size}
        )

    def get_installment(self, plan_id: str) -> dict:
        """Get installment plan by ID. GET /installment-plans/{id}"""
        return self._get(f"/installment-plans/{plan_id}")

    def create_installment(self, data: dict) -> dict:
        """Create an installment plan. POST /installment-plans"""
        return self._post("/installment-plans", data)

    def update_installment(self, plan_id: str, data: dict) -> dict:
        """Update an installment plan. PUT /installment-plans/{id}"""
        return self._put(f"/installment-plans/{plan_id}", data)

    # ======================== Budgets ========================

    def list_budgets(
        self, year_month: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict:
        """List budgets. GET /budgets"""
        return self._get(
            "/budgets", {"year_month": year_month, "page": page, "page_size": page_size}
        )

    def upsert_budget(self, data: dict) -> dict:
        """Create or update a budget. POST /budgets"""
        return self._post("/budgets", data)

    def get_budget_status(self, year_month: str) -> dict:
        """Get budget consumption status. GET /budgets/{year_month}/status"""
        return self._get(f"/budgets/{year_month}/status")

    # ======================== Transfers ========================

    def transfer(self, data: dict) -> list[dict]:
        """Execute a wallet-to-wallet transfer. POST /transfer"""
        return self._post("/transfer", data)

    # ======================== Summary / Analytics ========================

    def monthly_summary(self, year_month: str) -> dict:
        """Get monthly summary. GET /summary/{year_month}"""
        return self._get(f"/summary/{year_month}")

    def monthly_trends(self, months: int = 6) -> list[dict]:
        """Get multi-month spending trends. GET /insights"""
        return self._get("/insights", {"months": months})

    # ======================== Trash ========================

    def list_trash(self, entity_type: str, page: int = 1, page_size: int = 20) -> dict:
        """List soft-deleted items. GET /trash/{entity_type}"""
        return self._get(f"/trash/{entity_type}", {"page": page, "page_size": page_size})

    def restore_from_trash(self, entity_type: str, entity_id: str) -> dict:
        """Restore a soft-deleted item. POST /trash/{entity_type}/{id}/restore"""
        return self._post(f"/trash/{entity_type}/{entity_id}/restore")

    def purge_from_trash(self, entity_type: str, entity_id: str) -> None:
        """Permanently delete. DELETE /trash/{entity_type}/{id}"""
        self._delete(f"/trash/{entity_type}/{entity_id}")
