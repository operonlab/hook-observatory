"""Tests for wallet snapshot versioning, diff, and gap analysis.

Tests cover:
- Snapshot version auto-increment on sync
- Snapshot diff calculation
- Gap analysis — fully reconciled (gap=0)
- Gap analysis — with gap
- Global snapshot covering all active wallets
- _compute_period_delta helper
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.modules.finance.models import Wallet, WalletSnapshot
from src.modules.finance.schemas import (
    GapAnalysisResponse,
    GlobalSnapshotResponse,
    GlobalSnapshotSummary,
    SnapshotDiffResponse,
    WalletSnapshotResponse,
    WalletSyncRequest,
)
from src.modules.finance.services import (
    WalletService,
)

# ======================== Fixtures ========================


def _make_wallet(**overrides) -> MagicMock:
    """Create a mock wallet with sensible defaults."""
    defaults = {
        "id": "w" * 32,
        "space_id": "default",
        "created_by": "u" * 32,
        "name": "TestBank",
        "type": "bank_account",
        "currency": "TWD",
        "initial_balance": Decimal("10000"),
        "current_balance": Decimal("15000"),
        "credit_limit": None,
        "icon": None,
        "color": None,
        "sort_order": 0,
        "is_active": True,
        "is_private": False,
        "sync_provider": "manual",
        "last_synced_at": None,
        "deleted_at": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    w = MagicMock(spec=Wallet)
    for k, v in defaults.items():
        setattr(w, k, v)
    return w


def _make_snapshot(**overrides) -> MagicMock:
    """Create a mock snapshot with sensible defaults."""
    defaults = {
        "id": "s" * 32,
        "space_id": "default",
        "created_by": "u" * 32,
        "wallet_id": "w" * 32,
        "synced_balance": Decimal("15000"),
        "calculated_balance": Decimal("15000"),
        "snapshot_type": "reconciliation",
        "notes": None,
        "synced_at": datetime(2026, 3, 1, tzinfo=UTC),
        "version": 1,
        "batch_id": None,
        "metadata_json": None,
        "deleted_at": None,
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    s = MagicMock(spec=WalletSnapshot)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ======================== Schema Tests ========================


class TestSchemas:
    def test_wallet_snapshot_response_has_version(self):
        resp = WalletSnapshotResponse(
            id="a" * 32,
            space_id="default",
            created_by="u" * 32,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            wallet_id="w" * 32,
            synced_balance=Decimal("10000"),
            calculated_balance=Decimal("9500"),
            difference=Decimal("500"),
            synced_at=datetime.now(UTC),
            version=3,
            batch_id="b" * 32,
            metadata_json={"wallet_type": "bank_account"},
        )
        assert resp.version == 3
        assert resp.batch_id == "b" * 32
        assert resp.metadata_json["wallet_type"] == "bank_account"

    def test_snapshot_diff_response(self):
        resp = SnapshotDiffResponse(
            wallet_id="w" * 32,
            from_version=1,
            to_version=3,
            from_synced_balance=Decimal("10000"),
            to_synced_balance=Decimal("15000"),
            balance_delta=Decimal("5000"),
            delta_pct=50.0,
            from_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
            to_synced_at=datetime(2026, 3, 1, tzinfo=UTC),
            period_days=59,
        )
        assert resp.balance_delta == Decimal("5000")
        assert resp.delta_pct == 50.0

    def test_gap_analysis_reconciled(self):
        resp = GapAnalysisResponse(
            wallet_id="w" * 32,
            from_version=1,
            to_version=2,
            snapshot_delta=Decimal("5000"),
            transaction_sum=Decimal("5000"),
            gap=Decimal("0"),
            gap_pct=0.0,
            is_reconciled=True,
            transactions=[],
            from_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
            to_synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        assert resp.is_reconciled is True
        assert resp.gap == Decimal("0")

    def test_gap_analysis_with_gap(self):
        resp = GapAnalysisResponse(
            wallet_id="w" * 32,
            from_version=1,
            to_version=2,
            snapshot_delta=Decimal("5000"),
            transaction_sum=Decimal("4500"),
            gap=Decimal("500"),
            gap_pct=10.0,
            is_reconciled=False,
            transactions=[],
            from_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
            to_synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        assert resp.is_reconciled is False
        assert resp.gap == Decimal("500")

    def test_global_snapshot_response(self):
        resp = GlobalSnapshotResponse(
            batch_id="b" * 32,
            snapshot_count=3,
            total_net_worth=Decimal("100000"),
            snapshots=[],
            created_at=datetime.now(UTC),
        )
        assert resp.snapshot_count == 3
        assert resp.total_net_worth == Decimal("100000")

    def test_global_snapshot_summary(self):
        resp = GlobalSnapshotSummary(
            batch_id="b" * 32,
            snapshot_count=3,
            total_net_worth=Decimal("100000"),
            created_at=datetime.now(UTC),
        )
        assert resp.batch_id == "b" * 32


# ======================== Service Tests ========================


class TestSyncVersioning:
    """Test that sync() auto-increments version numbers."""

    def _setup_sync_db(self, wallet, max_version=0):
        """Create a properly mocked db for sync tests."""
        db = AsyncMock()
        db.get.return_value = wallet

        scalar_mock = MagicMock()
        scalar_mock.scalar_one.return_value = max_version
        db.execute.return_value = scalar_mock

        now = datetime(2026, 3, 19, tzinfo=UTC)
        # Capture the snapshot object when db.add is called
        captured = {}

        def capture_add(obj):
            captured["snapshot"] = obj

        db.add = MagicMock(side_effect=capture_add)

        async def mock_refresh(obj):
            # Simulate DB assigning timestamps and server defaults after flush
            if hasattr(obj, "created_at") and obj.created_at is None:
                obj.created_at = now
            if hasattr(obj, "updated_at") and obj.updated_at is None:
                obj.updated_at = now
            if hasattr(obj, "synced_at") and obj.synced_at is None:
                obj.synced_at = now

        db.refresh = AsyncMock(side_effect=mock_refresh)
        return db, captured

    @pytest.mark.asyncio
    async def test_sync_first_snapshot_is_v1(self):
        """First sync for a wallet should create version 1."""
        wallet = _make_wallet()
        db, captured = self._setup_sync_db(wallet, max_version=0)

        svc = WalletService()
        data = WalletSyncRequest(synced_balance=Decimal("15000"))

        with patch("src.modules.finance.services.event_bus"):
            with patch("src.modules.finance.services._uuid7_hex", return_value="x" * 32):
                result = await svc.sync(db, "w" * 32, data, "default")

        assert result.version == 1

    @pytest.mark.asyncio
    async def test_sync_increments_version(self):
        """Subsequent syncs should increment version."""
        wallet = _make_wallet()
        db, captured = self._setup_sync_db(wallet, max_version=3)

        svc = WalletService()
        data = WalletSyncRequest(synced_balance=Decimal("20000"))

        with patch("src.modules.finance.services.event_bus"):
            with patch("src.modules.finance.services._uuid7_hex", return_value="x" * 32):
                result = await svc.sync(db, "w" * 32, data, "default")

        assert result.version == 4

    @pytest.mark.asyncio
    async def test_sync_includes_metadata(self):
        """Sync should capture wallet metadata in the snapshot."""
        wallet = _make_wallet(name="MyBank", type="bank_account", currency="TWD")
        db, captured = self._setup_sync_db(wallet, max_version=0)

        svc = WalletService()
        data = WalletSyncRequest(synced_balance=Decimal("15000"))

        with patch("src.modules.finance.services.event_bus"):
            with patch("src.modules.finance.services._uuid7_hex", return_value="x" * 32):
                result = await svc.sync(db, "w" * 32, data, "default")

        assert result.metadata_json is not None
        assert result.metadata_json["wallet_name"] == "MyBank"
        assert result.metadata_json["wallet_type"] == "bank_account"
        assert result.metadata_json["currency"] == "TWD"


class TestDiffSnapshots:
    """Test snapshot diff calculation."""

    def _mock_snapshot_pair_db(self, from_snap, to_snap):
        """Create db mock for _get_snapshot_pair (single query returning list)."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [from_snap, to_snap]
        db.execute.return_value = result
        return db

    @pytest.mark.asyncio
    async def test_diff_positive_delta(self):
        """Diff should show positive balance change."""
        from_snap = _make_snapshot(
            version=1,
            synced_balance=Decimal("10000"),
            synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        to_snap = _make_snapshot(
            version=2,
            synced_balance=Decimal("15000"),
            synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db = self._mock_snapshot_pair_db(from_snap, to_snap)

        svc = WalletService()
        result = await svc.diff_snapshots(db, "w" * 32, 1, 2)

        assert isinstance(result, SnapshotDiffResponse)
        assert result.balance_delta == Decimal("5000")
        assert result.delta_pct == 50.0
        assert result.period_days == 31

    @pytest.mark.asyncio
    async def test_diff_negative_delta(self):
        """Diff should show negative balance change."""
        from_snap = _make_snapshot(
            version=1,
            synced_balance=Decimal("20000"),
            synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        to_snap = _make_snapshot(
            version=2,
            synced_balance=Decimal("15000"),
            synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db = self._mock_snapshot_pair_db(from_snap, to_snap)

        svc = WalletService()
        result = await svc.diff_snapshots(db, "w" * 32, 1, 2)

        assert result.balance_delta == Decimal("-5000")
        assert result.delta_pct == -25.0


class TestGapAnalysis:
    """Test gap analysis (sandwich reconciliation)."""

    def _mock_gap_db(self, from_snap, to_snap):
        """Create db mock for gap_analysis (_get_snapshot_pair returns list)."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [from_snap, to_snap]
        db.execute.return_value = result
        return db

    @pytest.mark.asyncio
    async def test_gap_zero_reconciled(self):
        """When snapshot delta == transaction sum, gap should be 0."""
        from_snap = _make_snapshot(
            version=1,
            synced_balance=Decimal("10000"),
            synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        to_snap = _make_snapshot(
            version=2,
            synced_balance=Decimal("15000"),
            synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db = self._mock_gap_db(from_snap, to_snap)

        svc = WalletService()

        with patch(
            "src.modules.finance.services._compute_period_delta",
            return_value=(Decimal("5000"), []),
        ):
            result = await svc.gap_analysis(db, "w" * 32, 1, 2)

        assert isinstance(result, GapAnalysisResponse)
        assert result.is_reconciled is True
        assert result.gap == Decimal("0")
        assert result.snapshot_delta == Decimal("5000")
        assert result.transaction_sum == Decimal("5000")

    @pytest.mark.asyncio
    async def test_gap_nonzero_not_reconciled(self):
        """When there's a gap, is_reconciled should be False."""
        from_snap = _make_snapshot(
            version=1,
            synced_balance=Decimal("10000"),
            synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        to_snap = _make_snapshot(
            version=2,
            synced_balance=Decimal("15000"),
            synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db = self._mock_gap_db(from_snap, to_snap)

        svc = WalletService()

        # Transaction sum is 4000 but snapshot delta is 5000 → gap = 1000
        with patch(
            "src.modules.finance.services._compute_period_delta",
            return_value=(Decimal("4000"), []),
        ):
            result = await svc.gap_analysis(db, "w" * 32, 1, 2)

        assert result.is_reconciled is False
        assert result.gap == Decimal("1000")
        assert result.snapshot_delta == Decimal("5000")
        assert result.transaction_sum == Decimal("4000")

    @pytest.mark.asyncio
    async def test_gap_within_tolerance(self):
        """Gap < 1 should still be reconciled (tolerance for rounding)."""
        from_snap = _make_snapshot(
            version=1,
            synced_balance=Decimal("10000"),
            synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        to_snap = _make_snapshot(
            version=2,
            synced_balance=Decimal("15000.5000"),
            synced_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db = self._mock_gap_db(from_snap, to_snap)

        svc = WalletService()

        # delta = 5000.5, txn_sum = 5000 → gap = 0.5 < 1 → reconciled
        with patch(
            "src.modules.finance.services._compute_period_delta",
            return_value=(Decimal("5000"), []),
        ):
            result = await svc.gap_analysis(db, "w" * 32, 1, 2)

        assert result.is_reconciled is True
        assert result.gap == Decimal("0.5000")


class TestGlobalSnapshot:
    """Test global snapshot creation."""

    def _setup_global_db(self, wallets):
        """Create a properly mocked db for global snapshot tests."""
        from collections import namedtuple

        db = AsyncMock()
        now = datetime(2026, 3, 19, tzinfo=UTC)

        # _calc_balance_components returns a Row with .income/.expense/.fees
        BalanceRow = namedtuple("BalanceRow", ["income", "expense", "fees"])
        zero_row = BalanceRow(income=Decimal("0"), expense=Decimal("0"), fees=Decimal("0"))

        call_count = 0

        def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Wallet query
                result.scalars.return_value.all.return_value = wallets
            else:
                # _calc_balance_components agg query returns .one()
                result.one.return_value = zero_row
                # transfer_in and max_version queries return .scalar_one()
                result.scalar_one.return_value = Decimal("0")
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.add = MagicMock()

        async def mock_refresh(obj):
            # Simulate DB assigning timestamps
            if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
                obj.updated_at = now

        db.refresh = AsyncMock(side_effect=mock_refresh)
        return db

    @pytest.mark.asyncio
    async def test_global_snapshot_covers_all_active_wallets(self):
        """Global snapshot should create one snapshot per active wallet."""
        wallet1 = _make_wallet(id="a" * 32, name="Bank", current_balance=Decimal("50000"))
        wallet2 = _make_wallet(
            id="b" * 32, name="Cash", type="cash", current_balance=Decimal("5000")
        )
        db = self._setup_global_db([wallet1, wallet2])

        svc = WalletService()

        with patch("src.modules.finance.services.event_bus"):
            with patch("src.modules.finance.services._uuid7_hex", return_value="x" * 32):
                result = await svc.create_global_snapshot(db, "default", user_id="u" * 32)

        assert isinstance(result, GlobalSnapshotResponse)
        assert result.snapshot_count == 2
        assert result.total_net_worth == Decimal("55000")
        assert result.batch_id == "x" * 32

    @pytest.mark.asyncio
    async def test_global_snapshot_shared_batch_id(self):
        """All snapshots in a global snapshot should share the same batch_id."""
        wallet1 = _make_wallet(id="a" * 32, current_balance=Decimal("10000"))
        db = self._setup_global_db([wallet1])

        svc = WalletService()

        with patch("src.modules.finance.services.event_bus"):
            with patch(
                "src.modules.finance.services._uuid7_hex", return_value="batch123" + "0" * 24
            ):
                result = await svc.create_global_snapshot(db, "default")

        assert len(result.snapshots) == 1
        assert result.snapshots[0].batch_id == "batch123" + "0" * 24
