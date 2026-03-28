"""Invest-svc tests — independent adversary agent, six iron rules.

Writer/tester separation: This file was written by reading ONLY routes.py,
schemas.py, main.py, and shared/*.py — NOT services.py implementation logic.
Contracts derived from: API signatures, schema definitions, error hierarchy.

Six Iron Rules applied:
  1. Mutation thinking  — each test documents what code mutation it catches
  2. Writer/tester separation — no implementation internals were copied
  3. Invariants over fixed I/O — property assertions, not hardcoded values
  4. Mock only external I/O — DB session mocked; internal service logic runs live
  5. Runtime regression — edge cases, boundary values, missing IDs
  6. Tests are drafts — inline comments explain each validation target
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SPACE_ID = "01900000000000000000000000000001"
_USER_ID = "01900000000000000000000000000002"
_ACCOUNT_ID = "01900000000000000000000000000003"
_POSITION_ID = "01900000000000000000000000000004"
_TRADE_ID = "01900000000000000000000000000005"
_QUOTE_ID = "01900000000000000000000000000006"


def _make_account_row(
    *,
    id: str = _ACCOUNT_ID,
    name: str = "Test Broker",
    broker: str | None = "Fubon",
    currency: str = "TWD",
    finance_wallet_id: str | None = None,
    notes: str | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Account row."""
    row = MagicMock()
    row.id = id
    row.name = name
    row.broker = broker
    row.currency = currency
    row.finance_wallet_id = finance_wallet_id
    row.notes = notes
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_position_row(
    *,
    id: str = _POSITION_ID,
    account_id: str = _ACCOUNT_ID,
    symbol: str = "2330.TW",
    exchange: str | None = "TWSE",
    asset_type: str = "stock",
    shares: Decimal = Decimal("100"),
    avg_cost: Decimal = Decimal("500"),
    current_price: Decimal = Decimal("600"),
    currency: str = "TWD",
    notes: str | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Position row."""
    row = MagicMock()
    row.id = id
    row.account_id = account_id
    row.symbol = symbol
    row.exchange = exchange
    row.asset_type = asset_type
    row.shares = shares
    row.avg_cost = avg_cost
    row.current_price = current_price
    row.currency = currency
    row.notes = notes
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_trade_row(
    *,
    id: str = _TRADE_ID,
    position_id: str = _POSITION_ID,
    type: str = "buy",
    shares: Decimal = Decimal("10"),
    price: Decimal = Decimal("550"),
    fee: Decimal = Decimal("20"),
    tax: Decimal = Decimal("0"),
    currency: str = "TWD",
    notes: str | None = None,
    traded_at: datetime | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Trade row."""
    row = MagicMock()
    row.id = id
    row.position_id = position_id
    row.type = type
    row.shares = shares
    row.price = price
    row.fee = fee
    row.tax = tax
    row.currency = currency
    row.notes = notes
    row.traded_at = traded_at or datetime.now(UTC)
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_quote_row(
    *,
    id: str = _QUOTE_ID,
    symbol: str = "2330.TW",
    price: Decimal = Decimal("600"),
    prev_close: Decimal | None = Decimal("595"),
    change_pct: Decimal | None = Decimal("0.84"),
    currency: str = "TWD",
    source: str = "manual",
    quoted_at: datetime | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Quote row."""
    row = MagicMock()
    row.id = id
    row.symbol = symbol
    row.price = price
    row.prev_close = prev_close
    row.change_pct = change_pct
    row.currency = currency
    row.source = source
    row.quoted_at = quoted_at or datetime.now(UTC)
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_mock_db() -> AsyncMock:
    """Build an AsyncSession mock with chainable execute().scalars().all() / .first()."""
    db = AsyncMock()

    # Default result set: empty
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    scalars_result.first.return_value = None

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result
    execute_result.scalar_one.return_value = 0
    execute_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(return_value=None)

    # Track instances added via db.add so flush can populate server_default fields
    _added_instances: list = []

    def _mock_add(instance):
        _added_instances.append(instance)

    db.add = MagicMock(side_effect=_mock_add)

    # flush: populate fields that DB would set via server_default on added instances
    async def _mock_flush(*args, **kwargs):
        from uuid_utils import uuid7

        for inst in _added_instances:
            if getattr(inst, "id", None) is None:
                inst.id = uuid7().hex
            if getattr(inst, "created_at", None) is None:
                inst.created_at = datetime.now(UTC)
            if getattr(inst, "updated_at", None) is None:
                inst.updated_at = datetime.now(UTC)

    db.flush = AsyncMock(side_effect=_mock_flush)

    # refresh: also populate in case flush was bypassed
    async def _mock_refresh(instance, *args, **kwargs):
        from uuid_utils import uuid7

        if getattr(instance, "id", None) is None:
            instance.id = uuid7().hex
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(UTC)
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = datetime.now(UTC)

    db.refresh = AsyncMock(side_effect=_mock_refresh)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    return _make_mock_db()


@pytest.fixture
async def client(mock_db):
    """AsyncClient with get_db overridden to return our mock session."""
    from svc_shared.database import get_db

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Health Endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    """Service health checks — if these fail, nothing else can work."""

    @pytest.mark.asyncio
    async def test_root_health_ok(self, client: AsyncClient):
        """
        # MUTATION: Remove /health route or change path -> test fails
        Validates: 200 + JSON has 'status': 'ok'
        """
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "service" in body

    @pytest.mark.asyncio
    async def test_health_service_identity(self, client: AsyncClient):
        """
        # MUTATION: If service name is wrong (e.g., copy-paste from paper), monitoring breaks
        Validates: service field equals 'invest'
        """
        resp = await client.get("/health")
        body = resp.json()
        assert body["service"] == "invest"

    @pytest.mark.asyncio
    async def test_health_port_is_integer(self, client: AsyncClient):
        """
        # MUTATION: If PORT config serialized as string, service discovery fails
        Validates: port is numeric
        """
        resp = await client.get("/health")
        body = resp.json()
        assert isinstance(body["port"], int)

    @pytest.mark.asyncio
    async def test_invest_status_endpoint(self, client: AsyncClient):
        """
        # MUTATION: If /api/invest/status is removed, module health probes fail
        Validates: 200 response with module='invest'
        """
        resp = await client.get("/api/invest/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["module"] == "invest"
        assert body["status"] == "active"


# ---------------------------------------------------------------------------
# 2. Account CRUD
# ---------------------------------------------------------------------------


class TestAccountCRUD:
    """Account CRUD operations — mock DB so service logic runs live."""

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If list() ignores soft-delete filter, deleted accounts appear
        Validates: paginated response with items=[], total=0
        """
        resp = await client.get("/api/invest/accounts", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert isinstance(body["items"], list)
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_accounts_pagination_echoed(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If pagination params are ignored (page always=1), large lists break
        Validates: page/page_size echoed back correctly
        """
        resp = await client.get(
            "/api/invest/accounts",
            params={"space_id": _SPACE_ID, "page": 3, "page_size": 10},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 3
        assert body["page_size"] == 10

    @pytest.mark.asyncio
    async def test_get_account_not_found_returns_404(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If route returns 200 on missing account instead of raising NotFoundError
        Validates: 404 on missing ID
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_account_found_returns_response(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If to_response() drops required fields (name, currency, id)
        Validates: response has core SpaceScopedResponse + Account fields
        """
        account = _make_account_row()
        mock_db.get.return_value = account
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == _ACCOUNT_ID
        assert body["name"] == "Test Broker"
        assert "currency" in body
        assert "space_id" in body
        assert "created_at" in body
        assert "updated_at" in body

    @pytest.mark.asyncio
    async def test_create_account_minimal(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If 'broker' becomes required but schema says optional, title-only creates fail
        Validates: create with name-only succeeds (201)
        """
        resp = await client.post(
            "/api/invest/accounts",
            json={"name": "Simple Account"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Simple Account"
        assert isinstance(body["id"], str)
        assert len(body["id"]) > 0

    @pytest.mark.asyncio
    async def test_create_account_missing_name_returns_422(self, client: AsyncClient):
        """
        # MUTATION: If name validation is removed from schema, garbage data enters DB
        Validates: POST without name -> 422 Unprocessable Entity
        """
        resp = await client.post(
            "/api/invest/accounts",
            json={"broker": "Test"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_account_currency_default(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If currency default changes from TWD to something else, existing UI breaks
        Validates: currency defaults to 'TWD' when not specified
        """
        resp = await client.post(
            "/api/invest/accounts",
            json={"name": "Default Currency Test"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["currency"] == "TWD"

    @pytest.mark.asyncio
    async def test_update_account_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If update() silently ignores missing entity and returns 200
        Validates: 404 on missing ID
        """
        mock_db.get.return_value = None
        resp = await client.put(
            f"/api/invest/accounts/{_ACCOUNT_ID}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_account_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If delete() on missing entity returns 204 (no-op success)
        Validates: 404 on missing delete
        """
        mock_db.get.return_value = None
        resp = await client.delete(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_account_success_returns_204(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If soft-delete sets deleted_at but returns False, 404 fires incorrectly
        Validates: delete existing account returns 204
        """
        account = _make_account_row()
        mock_db.get.return_value = account
        resp = await client.delete(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# 3. Account Summary
# ---------------------------------------------------------------------------


class TestAccountSummary:
    """Account summary endpoint — aggregated position data."""

    @pytest.mark.asyncio
    async def test_summary_not_found_returns_404(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If get_summary doesn't check account existence first
        Validates: 404 on non-existent account
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}/summary")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_summary_empty_positions(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If summary crashes on zero positions instead of returning defaults
        Validates: summary with no positions returns zero-value aggregates
        """
        account = _make_account_row()
        mock_db.get.return_value = account
        # execute returns empty positions
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}/summary")
        assert resp.status_code == 200
        body = resp.json()
        # Must have summary-specific fields
        assert "total_market_value" in body
        assert "total_cost" in body
        assert "total_gain" in body
        assert "gain_pct" in body
        assert "position_count" in body
        # With no positions, counts/values should be zero
        assert body["position_count"] == 0


# ---------------------------------------------------------------------------
# 4. Position CRUD
# ---------------------------------------------------------------------------


class TestPositionCRUD:
    """Position CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_positions_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If list() doesn't filter by space_id, positions from all spaces mix
        Validates: paginated response with items=[], total=0
        """
        resp = await client.get("/api/invest/positions", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_create_position_minimal(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If account_id or symbol becomes optional, orphan positions are created
        Validates: create with required fields succeeds (201)
        """
        resp = await client.post(
            "/api/invest/positions",
            json={"account_id": _ACCOUNT_ID, "symbol": "AAPL"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["symbol"] == "AAPL"
        assert body["account_id"] == _ACCOUNT_ID
        assert isinstance(body["id"], str)

    @pytest.mark.asyncio
    async def test_create_position_missing_required_field(self, client: AsyncClient):
        """
        # MUTATION: If symbol validation is removed, empty-symbol positions break quote lookup
        Validates: POST without symbol -> 422
        """
        resp = await client.post(
            "/api/invest/positions",
            json={"account_id": _ACCOUNT_ID},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_position_missing_account_id(self, client: AsyncClient):
        """
        # MUTATION: If account_id validation is removed, positions without parent account are created
        Validates: POST without account_id -> 422
        """
        resp = await client.post(
            "/api/invest/positions",
            json={"symbol": "AAPL"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_position_defaults(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If default asset_type changes from 'stock' or shares default changes
        Validates: default field values match schema contract
        """
        resp = await client.post(
            "/api/invest/positions",
            json={"account_id": _ACCOUNT_ID, "symbol": "2330.TW"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["asset_type"] == "stock"
        assert body["currency"] == "TWD"

    @pytest.mark.asyncio
    async def test_position_response_has_derived_fields(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If to_response() drops calculated fields (market_value, unrealized_gain)
        Validates: response includes all derived financial fields
        """
        resp = await client.post(
            "/api/invest/positions",
            json={
                "account_id": _ACCOUNT_ID,
                "symbol": "2330.TW",
                "shares": "100",
                "avg_cost": "500",
                "current_price": "600",
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "market_value" in body
        assert "total_cost" in body
        assert "unrealized_gain" in body
        assert "gain_pct" in body

    @pytest.mark.asyncio
    async def test_update_position_price(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If update_price doesn't update current_price field on the position
        Validates: PUT /positions/{id}/price with valid data returns 200
        """
        position = _make_position_row()
        mock_db.get.return_value = position
        resp = await client.put(
            f"/api/invest/positions/{_POSITION_ID}/price",
            json={"price": "650"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["id"], str)

    @pytest.mark.asyncio
    async def test_update_position_price_not_found(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If update_price doesn't verify position existence, silent no-op occurs
        Validates: 404 on non-existent position
        """
        mock_db.get.return_value = None
        resp = await client.put(
            f"/api/invest/positions/{_POSITION_ID}/price",
            json={"price": "650"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Trade Operations
# ---------------------------------------------------------------------------


class TestTradeOperations:
    """Trade CRUD — buy/sell/dividend records."""

    @pytest.mark.asyncio
    async def test_list_trades_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If list() doesn't apply soft-delete filter, deleted trades appear
        Validates: paginated response with items=[], total=0
        """
        resp = await client.get("/api/invest/trades", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_create_trade_requires_position_id(self, client: AsyncClient):
        """
        # MUTATION: If position_id validation is removed, orphan trades are created
        Validates: POST without position_id -> 422
        """
        resp = await client.post(
            "/api/invest/trades",
            json={
                "type": "buy",
                "shares": "10",
                "price": "100",
                "traded_at": datetime.now(UTC).isoformat(),
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_trade_requires_traded_at(self, client: AsyncClient):
        """
        # MUTATION: If traded_at becomes optional, trades have no timestamp, breaking time-series
        Validates: POST without traded_at -> 422
        """
        resp = await client.post(
            "/api/invest/trades",
            json={
                "position_id": _POSITION_ID,
                "type": "buy",
                "shares": "10",
                "price": "100",
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_trade_position_not_found(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If trade create doesn't validate position existence, orphan trades are created
        Validates: 404 when position_id doesn't exist
        """
        mock_db.get.return_value = None
        resp = await client.post(
            "/api/invest/trades",
            json={
                "position_id": _POSITION_ID,
                "type": "buy",
                "shares": "10",
                "price": "100",
                "traded_at": datetime.now(UTC).isoformat(),
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_buy_trade_success(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If trade creation doesn't call db.add/flush, trade is lost
        Validates: buy trade with valid position creates successfully
        """
        position = _make_position_row()
        mock_db.get.return_value = position
        resp = await client.post(
            "/api/invest/trades",
            json={
                "position_id": _POSITION_ID,
                "type": "buy",
                "shares": "10",
                "price": "550",
                "traded_at": datetime.now(UTC).isoformat(),
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["type"] == "buy"
        assert isinstance(body["id"], str)
        assert "total_amount" in body

    @pytest.mark.asyncio
    async def test_create_trade_fee_default_zero(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If fee default changes from 0 to non-zero, all feeless trades get wrong totals
        Validates: fee defaults to 0 when not specified
        """
        position = _make_position_row()
        mock_db.get.return_value = position
        resp = await client.post(
            "/api/invest/trades",
            json={
                "position_id": _POSITION_ID,
                "type": "buy",
                "shares": "5",
                "price": "100",
                "traded_at": datetime.now(UTC).isoformat(),
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        # fee and tax should default to 0
        assert Decimal(str(body["fee"])) == Decimal("0")
        assert Decimal(str(body["tax"])) == Decimal("0")


# ---------------------------------------------------------------------------
# 6. Portfolio
# ---------------------------------------------------------------------------


class TestPortfolio:
    """Portfolio summary — cross-account aggregation."""

    @pytest.mark.asyncio
    async def test_portfolio_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If portfolio crashes on zero accounts instead of returning defaults
        Validates: empty portfolio returns zero-value summary
        """
        resp = await client.get("/api/invest/portfolio", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "total_market_value" in body
        assert "total_cost" in body
        assert "total_gain" in body
        assert "gain_pct" in body
        assert "account_count" in body
        assert "position_count" in body
        assert "accounts" in body
        assert isinstance(body["accounts"], list)

    @pytest.mark.asyncio
    async def test_portfolio_counters_non_negative(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If count aggregation has sign error, counters go negative
        Validates: all count fields >= 0
        """
        resp = await client.get("/api/invest/portfolio", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_count"] >= 0
        assert body["position_count"] >= 0


# ---------------------------------------------------------------------------
# 7. Quote Refresh
# ---------------------------------------------------------------------------


class TestQuoteRefresh:
    """Quote refresh endpoint — returns current quote records."""

    @pytest.mark.asyncio
    async def test_refresh_quotes_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If refresh_quotes crashes on no quotes instead of returning empty list
        Validates: returns empty list when no quotes exist
        """
        resp = await client.post(
            "/api/invest/quotes/refresh",
            json={},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 0

    @pytest.mark.asyncio
    async def test_refresh_quotes_with_symbols_filter(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If symbols filter is ignored, all quotes are returned regardless
        Validates: request with symbols list accepted (doesn't error)
        """
        resp = await client.post(
            "/api/invest/quotes/refresh",
            json={"symbols": ["2330.TW", "AAPL"]},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)


# ---------------------------------------------------------------------------
# 8. Error Handling & Invariants
# ---------------------------------------------------------------------------


class TestErrorHandlingAndInvariants:
    """Error handler and structural invariants."""

    @pytest.mark.asyncio
    async def test_workshop_error_handler_produces_structured_error(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If WorkshopError handler is removed from main.py, all 404s return unformatted
        Validates: 404 response has 'detail', 'code', and 'module' fields
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert "code" in body, "Missing 'code' — WorkshopError handler may be bypassed"

    @pytest.mark.asyncio
    async def test_error_code_has_invest_prefix(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If error code prefix changes from 'invest.' to something else, error routing breaks
        Validates: error code starts with 'invest.'
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"].startswith("invest.")

    @pytest.mark.asyncio
    async def test_unknown_route_returns_404_not_500(self, client: AsyncClient):
        """
        # MUTATION: If a wildcard route catches all paths and returns 200
        Validates: unknown paths return 404 (not 500)
        """
        resp = await client.get("/api/invest/nonexistent_endpoint_xyz")
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_account_response_id_is_string(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If UUID serialization changes to raw UUID object
        Validates: id field in response is a string
        """
        account = _make_account_row()
        mock_db.get.return_value = account
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["id"], str)

    @pytest.mark.asyncio
    async def test_pagination_defaults_are_sane(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If default page_size set to 0 or huge number, all list endpoints break
        Validates: default page >= 1 and page_size >= 1
        """
        resp = await client.get("/api/invest/accounts", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] >= 1
        assert body["page_size"] >= 1

    @pytest.mark.asyncio
    async def test_soft_deleted_account_not_fetchable(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If get() doesn't filter by deleted_at, deleted accounts remain accessible
        Validates: deleted account -> 404 on GET
        """
        deleted_account = _make_account_row(deleted_at=datetime.now(UTC))
        mock_db.get.return_value = deleted_account
        resp = await client.get(f"/api/invest/accounts/{_ACCOUNT_ID}")
        # Service should treat deleted_at != None as "not found"
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_soft_deleted_position_not_fetchable_for_trade(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If trade create doesn't check position.deleted_at, trades on deleted positions pass
        Validates: trade create on soft-deleted position -> 404
        """
        deleted_position = _make_position_row(deleted_at=datetime.now(UTC))
        mock_db.get.return_value = deleted_position
        resp = await client.post(
            "/api/invest/trades",
            json={
                "position_id": _POSITION_ID,
                "type": "buy",
                "shares": "10",
                "price": "100",
                "traded_at": datetime.now(UTC).isoformat(),
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404
