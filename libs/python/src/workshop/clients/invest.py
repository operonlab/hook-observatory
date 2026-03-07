"""Invest API client — Core module at /api/invest.

Wraps accounts, positions, trades, portfolio, and quote refresh endpoints.

Usage:
    from workshop.clients.invest import InvestClient

    client = InvestClient()
    accounts = client.list_accounts()
    portfolio = client.get_portfolio()
"""

from typing import Any

from ._base import BaseClient


class InvestError(Exception):
    """Raised on Invest API errors."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Invest error {status_code}: {detail}")


class InvestClient(BaseClient):
    """HTTP client for the Invest Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="invest", **kwargs)

    # ======================== Accounts ========================

    def list_accounts(self, page: int = 1, page_size: int = 20) -> dict:
        """List investment accounts. GET /accounts"""
        return self._get("/accounts", {"page": page, "page_size": page_size})

    def get_account(self, account_id: str) -> dict:
        """Get account by ID. GET /accounts/{account_id}"""
        return self._get(f"/accounts/{account_id}")

    def create_account(self, data: dict) -> dict:
        """Create an investment account. POST /accounts

        data keys:
            name (str): Account name.
            broker (str, optional): Broker name.
            currency (str): Currency code, default "TWD".
            finance_wallet_id (str, optional): Linked finance wallet ID.
            notes (str, optional): Free-form notes.
        """
        return self._post("/accounts", data)

    def update_account(self, account_id: str, data: dict) -> dict:
        """Update an investment account. PUT /accounts/{account_id}"""
        return self._put(f"/accounts/{account_id}", data)

    def get_account_summary(self, account_id: str) -> dict:
        """Get account summary including positions. GET /accounts/{account_id}/summary"""
        return self._get(f"/accounts/{account_id}/summary")

    # ======================== Positions ========================

    def list_positions(
        self,
        account_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List positions with optional account filter. GET /positions"""
        return self._get(
            "/positions",
            {"account_id": account_id, "page": page, "page_size": page_size},
        )

    def create_position(self, data: dict) -> dict:
        """Create a position. POST /positions

        data keys:
            account_id (str): Parent account ID.
            symbol (str): Ticker symbol.
            exchange (str, optional): Exchange code.
            asset_type (str): Asset type, default "stock".
            shares (float): Number of shares, default 0.
            avg_cost (float): Average cost per share, default 0.
            current_price (float): Current market price, default 0.
            currency (str): Currency code, default "TWD".
            notes (str, optional): Free-form notes.
        """
        return self._post("/positions", data)

    def update_position_price(self, position_id: str, price: float) -> dict:
        """Update the current price of a position. PUT /positions/{position_id}/price

        Args:
            position_id: Position UUID.
            price: New current market price.
        """
        return self._put(f"/positions/{position_id}/price", {"price": price})

    # ======================== Trades ========================

    def list_trades(
        self,
        position_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List trades with optional position filter. GET /trades"""
        return self._get(
            "/trades",
            {"position_id": position_id, "page": page, "page_size": page_size},
        )

    def create_trade(self, data: dict) -> dict:
        """Record a trade. POST /trades

        data keys:
            position_id (str): Parent position ID.
            type (str): Trade type — buy | sell | dividend | split.
            shares (float): Number of shares transacted.
            price (float): Price per share.
            fee (float): Brokerage fee, default 0.
            tax (float): Transaction tax, default 0.
            currency (str): Currency code, default "TWD".
            notes (str, optional): Free-form notes.
            traded_at (str): ISO-8601 datetime of the trade.
        """
        return self._post("/trades", data)

    # ======================== Portfolio / Quotes ========================

    def get_portfolio(self) -> dict:
        """Get overall portfolio summary. GET /portfolio"""
        return self._get("/portfolio")

    def refresh_quotes(self, symbols: list[str]) -> dict:
        """Refresh market quotes for given symbols. POST /quotes/refresh

        Args:
            symbols: List of ticker symbols to refresh (e.g. ["2330", "AAPL"]).
        """
        return self._post("/quotes/refresh", {"symbols": symbols})
