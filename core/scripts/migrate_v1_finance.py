#!/usr/bin/env python3
"""Migrate V1 finance data (pulso_finance schema) to V2 (finance schema).

Usage:
    cd core && uv run python3 scripts/migrate_v1_finance.py --space-id default
    cd core && uv run python3 scripts/migrate_v1_finance.py --space-id default --dry-run

Reads: pulso_finance.transactions, pulso_finance.transaction_tags,
       pulso_finance.subscriptions, pulso_finance.subscription_tags
Writes: finance.wallets, finance.categories, finance.transactions,
        finance.transaction_tags, finance.subscriptions

Idempotent: uses invoice_number='v1:{v1_id}' markers for transactions,
            name+space_id checks for wallets/categories/subscriptions.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Add core/src to path so we can import models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modules.finance.models import (
    Category,
    Subscription,
    Transaction,
    TransactionTag,
    Wallet,
)
from shared.models import _uuid7_hex

logger = structlog.get_logger()

# ======================== Constants ========================

DEFAULT_DB_URL = "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop"
DEFAULT_WALLET_NAME = "未分類"
DEFAULT_CATEGORY_NAME = "未分類"

# V1 payment_method text -> V2 wallet type mapping
_WALLET_TYPE_RULES: list[tuple[list[str], str]] = [
    (["信用卡"], "credit_card"),
    (["卡"], "credit_card"),
    (["現金"], "cash"),
    (["Apple Pay", "Google Pay", "Line Pay", "LINE Pay", "Pay"], "e_wallet"),
    (["轉帳", "ATM"], "bank_account"),
]


def _infer_wallet_type(payment_method: str) -> str:
    """Infer V2 wallet type from V1 payment_method text."""
    if not payment_method:
        return "cash"
    for keywords, wallet_type in _WALLET_TYPE_RULES:
        for kw in keywords:
            if kw in payment_method:
                return wallet_type
    return "cash"


# V1 renewal_json.kind -> V2 billing_cycle
_CYCLE_MAP: dict[str, str] = {
    "monthly": "monthly",
    "yearly": "yearly",
    "annual": "yearly",
    "weekly": "weekly",
    "custom": "monthly",  # fallback for custom
}


# ======================== V1 Data Reading ========================


async def read_v1_transactions(session_factory: async_sessionmaker) -> list[dict]:
    """Read all transactions from pulso_finance.transactions."""
    async with session_factory() as db:
        result = await db.execute(
            text("SELECT * FROM pulso_finance.transactions ORDER BY ts")
        )
        rows = result.mappings().all()
    logger.info("V1 transactions read", count=len(rows))
    return [dict(r) for r in rows]


async def read_v1_transaction_tags(session_factory: async_sessionmaker) -> dict[str, list[str]]:
    """Read all transaction tags, grouped by tx_id."""
    async with session_factory() as db:
        result = await db.execute(
            text("SELECT tx_id, tag FROM pulso_finance.transaction_tags")
        )
        rows = result.all()
    tag_map: dict[str, list[str]] = {}
    for tx_id, tag in rows:
        tag_map.setdefault(tx_id, []).append(tag)
    logger.info("V1 transaction tags read", tag_count=len(rows), tx_count=len(tag_map))
    return tag_map


async def read_v1_subscriptions(session_factory: async_sessionmaker) -> list[dict]:
    """Read all subscriptions from pulso_finance.subscriptions."""
    async with session_factory() as db:
        result = await db.execute(
            text("SELECT * FROM pulso_finance.subscriptions ORDER BY id")
        )
        rows = result.mappings().all()
    logger.info("V1 subscriptions read", count=len(rows))
    return [dict(r) for r in rows]


async def read_v1_subscription_tags(session_factory: async_sessionmaker) -> dict[str, list[str]]:
    """Read all subscription tags, grouped by sub_id."""
    async with session_factory() as db:
        result = await db.execute(
            text("SELECT sub_id, tag FROM pulso_finance.subscription_tags")
        )
        rows = result.all()
    tag_map: dict[str, list[str]] = {}
    for sub_id, tag in rows:
        tag_map.setdefault(sub_id, []).append(tag)
    logger.info("V1 subscription tags read", tag_count=len(rows), sub_count=len(tag_map))
    return tag_map


# ======================== Parsing Helpers ========================


def _safe_decimal(value: object) -> Decimal:
    """Convert a value to Decimal, defaulting to 0 on failure."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _parse_timestamp(ts_str: str | None) -> datetime:
    """Parse ISO 8601 timestamp string to timezone-aware datetime.

    Falls back to UTC now if parsing fails.
    """
    if not ts_str:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _parse_renewal_json(raw: str | None) -> tuple[str, int | None]:
    """Parse V1 renewal_json to (billing_cycle, billing_day).

    Returns ('monthly', None) as fallback.
    """
    if not raw:
        return "monthly", None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "monthly", None

    kind = data.get("kind", "monthly")
    billing_cycle = _CYCLE_MAP.get(kind, "monthly")
    billing_day = data.get("dayOfMonth")
    if billing_day is not None:
        try:
            billing_day = int(billing_day)
        except (ValueError, TypeError):
            billing_day = None
    return billing_cycle, billing_day


def _parse_data_json_notes(raw: str | None) -> str | None:
    """Extract 'note' or 'notes' field from V1 data_json blob."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data.get("note") or data.get("notes")


# ======================== Wallet Inference ========================


def build_wallet_map(
    v1_transactions: list[dict],
    v1_subscriptions: list[dict],
    space_id: str,
) -> dict[str, dict]:
    """Build a wallet map: payment_method -> wallet dict (with pre-generated uuid7 ID).

    Always includes a default "未分類" wallet for unmapped payment methods.
    """
    payment_methods: set[str] = set()
    for tx in v1_transactions:
        pm = (tx.get("payment_method") or "").strip()
        if pm:
            payment_methods.add(pm)
    for sub in v1_subscriptions:
        pm = (sub.get("payment_method") or "").strip()
        if pm:
            payment_methods.add(pm)

    wallet_map: dict[str, dict] = {}

    # Default wallet (always created)
    wallet_map[""] = {
        "id": _uuid7_hex(),
        "space_id": space_id,
        "name": DEFAULT_WALLET_NAME,
        "type": "cash",
        "currency": "TWD",
    }

    for pm in sorted(payment_methods):
        wallet_type = _infer_wallet_type(pm)
        wallet_map[pm] = {
            "id": _uuid7_hex(),
            "space_id": space_id,
            "name": pm,
            "type": wallet_type,
            "currency": "TWD",
        }

    logger.info(
        "Wallet map built",
        unique_payment_methods=len(payment_methods),
        wallets_to_create=len(wallet_map),
    )
    return wallet_map


# ======================== Category Inference ========================


def build_category_map(
    v1_transactions: list[dict],
    v1_subscriptions: list[dict],
    space_id: str,
) -> dict[str, dict]:
    """Build a category map: category_text -> category dict (with pre-generated uuid7 ID).

    Always includes a default "未分類" category for empty/null categories.
    """
    categories: set[str] = set()
    for tx in v1_transactions:
        cat = (tx.get("category") or "").strip()
        if cat:
            categories.add(cat)
    for sub in v1_subscriptions:
        cat = (sub.get("category") or "").strip()
        if cat:
            categories.add(cat)

    cat_map: dict[str, dict] = {}

    # Default category
    cat_map[""] = {
        "id": _uuid7_hex(),
        "space_id": space_id,
        "name": DEFAULT_CATEGORY_NAME,
    }

    for cat_name in sorted(categories):
        cat_map[cat_name] = {
            "id": _uuid7_hex(),
            "space_id": space_id,
            "name": cat_name,
        }

    logger.info(
        "Category map built",
        unique_categories=len(categories),
        categories_to_create=len(cat_map),
    )
    return cat_map


# ======================== Database Writes ========================


async def create_wallets(
    session_factory: async_sessionmaker,
    wallet_map: dict[str, dict],
    space_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Create V2 wallets. Returns (created, skipped)."""
    created = 0
    skipped = 0

    if dry_run:
        return len(wallet_map), 0

    async with session_factory() as db:
        async with db.begin():
            for _pm, w in wallet_map.items():
                # Check for existing wallet with same name in this space
                existing = (
                    await db.execute(
                        select(Wallet.id).where(
                            Wallet.space_id == space_id,
                            Wallet.name == w["name"],
                            Wallet.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    # Update the map to use existing ID for FK references
                    w["id"] = existing
                    skipped += 1
                    continue

                db.add(
                    Wallet(
                        id=w["id"],
                        space_id=w["space_id"],
                        name=w["name"],
                        type=w["type"],
                        currency=w["currency"],
                        initial_balance=Decimal("0"),
                        current_balance=Decimal("0"),
                        is_active=True,
                        is_private=False,
                    )
                )
                created += 1

    logger.info("Wallets created", created=created, skipped=skipped)
    return created, skipped


async def create_categories(
    session_factory: async_sessionmaker,
    cat_map: dict[str, dict],
    space_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Create V2 categories. Returns (created, skipped)."""
    created = 0
    skipped = 0

    if dry_run:
        return len(cat_map), 0

    async with session_factory() as db:
        async with db.begin():
            for _cat_text, c in cat_map.items():
                # Check for existing root-level category with same name
                existing = (
                    await db.execute(
                        select(Category.id).where(
                            Category.space_id == space_id,
                            Category.parent_id.is_(None),
                            Category.name == c["name"],
                            Category.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    c["id"] = existing
                    skipped += 1
                    continue

                db.add(
                    Category(
                        id=c["id"],
                        space_id=c["space_id"],
                        name=c["name"],
                        parent_id=None,
                        is_active=True,
                        is_private=False,
                    )
                )
                created += 1

    logger.info("Categories created", created=created, skipped=skipped)
    return created, skipped


async def migrate_transactions(
    session_factory: async_sessionmaker,
    v1_transactions: list[dict],
    v1_tag_map: dict[str, list[str]],
    wallet_map: dict[str, dict],
    cat_map: dict[str, dict],
    space_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Migrate V1 transactions to V2. Returns (migrated, skipped)."""
    migrated = 0
    skipped = 0

    if dry_run:
        # In dry-run, count how many would be new vs already existing
        async with session_factory() as db:
            for tx in v1_transactions:
                v1_id = tx["id"]
                marker = f"v1:{v1_id}"
                existing = (
                    await db.execute(
                        select(Transaction.id).where(
                            Transaction.invoice_number == marker,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                else:
                    migrated += 1
        return migrated, skipped

    async with session_factory() as db:
        async with db.begin():
            for tx in v1_transactions:
                v1_id = tx["id"]
                marker = f"v1:{v1_id}"

                # Idempotency check
                existing = (
                    await db.execute(
                        select(Transaction.id).where(
                            Transaction.invoice_number == marker,
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    skipped += 1
                    continue

                # Resolve wallet
                pm = (tx.get("payment_method") or "").strip()
                wallet_info = wallet_map.get(pm, wallet_map[""])
                wallet_id = wallet_info["id"]

                # Resolve category
                cat_text = (tx.get("category") or "").strip()
                cat_info = cat_map.get(cat_text, cat_map[""])
                category_id = cat_info["id"]

                # Parse fields
                tx_type = (tx.get("type") or "expense").strip().lower()
                if tx_type not in ("income", "expense", "transfer"):
                    tx_type = "expense"

                amount = _safe_decimal(tx.get("amount"))
                currency = (tx.get("currency") or "TWD").strip()
                merchant = tx.get("merchant")
                if merchant:
                    merchant = merchant.strip() or None
                note = tx.get("note")
                if note:
                    note = note.strip() or None
                transacted_at = _parse_timestamp(tx.get("ts"))

                v2_id = _uuid7_hex()

                db.add(
                    Transaction(
                        id=v2_id,
                        space_id=space_id,
                        created_by=None,
                        type=tx_type,
                        amount=amount,
                        currency=currency,
                        description=note,
                        merchant=merchant,
                        payment_method=pm or "cash",
                        payment_detail=None,
                        category_id=category_id,
                        wallet_id=wallet_id,
                        status="completed",
                        invoice_number=marker,
                        is_private=False,
                        transacted_at=transacted_at,
                    )
                )

                # Tags
                tags = v1_tag_map.get(v1_id, [])
                for tag_text in tags:
                    tag_text = tag_text.strip()
                    if tag_text:
                        db.add(
                            TransactionTag(
                                transaction_id=v2_id,
                                tag=tag_text,
                            )
                        )

                migrated += 1

    logger.info("Transactions migrated", migrated=migrated, skipped=skipped)
    return migrated, skipped


async def migrate_subscriptions(
    session_factory: async_sessionmaker,
    v1_subscriptions: list[dict],
    wallet_map: dict[str, dict],
    cat_map: dict[str, dict],
    space_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Migrate V1 subscriptions to V2. Returns (migrated, skipped)."""
    migrated = 0
    skipped = 0

    if dry_run:
        async with session_factory() as db:
            for sub in v1_subscriptions:
                name = (sub.get("name") or "").strip()
                existing = (
                    await db.execute(
                        select(Subscription.id).where(
                            Subscription.space_id == space_id,
                            Subscription.name == name,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                else:
                    migrated += 1
        return migrated, skipped

    async with session_factory() as db:
        async with db.begin():
            for sub in v1_subscriptions:
                name = (sub.get("name") or "").strip()
                if not name:
                    logger.warning("Skipping subscription with empty name", v1_id=sub.get("id"))
                    skipped += 1
                    continue

                # Idempotency: check by name + space_id
                existing = (
                    await db.execute(
                        select(Subscription.id).where(
                            Subscription.space_id == space_id,
                            Subscription.name == name,
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    skipped += 1
                    continue

                # Resolve wallet
                pm = (sub.get("payment_method") or "").strip()
                wallet_info = wallet_map.get(pm, wallet_map[""])
                wallet_id = wallet_info["id"]

                # Resolve category
                cat_text = (sub.get("category") or "").strip()
                cat_info = cat_map.get(cat_text, cat_map[""])
                category_id = cat_info["id"]

                # Parse renewal
                billing_cycle, billing_day = _parse_renewal_json(sub.get("renewal_json"))

                # Parse status
                active_flag = sub.get("active")
                if active_flag is not None:
                    status = "active" if int(active_flag) == 1 else "cancelled"
                else:
                    status = "active"

                amount = _safe_decimal(sub.get("amount"))
                currency = (sub.get("currency") or "TWD").strip()
                notes = _parse_data_json_notes(sub.get("data_json"))

                db.add(
                    Subscription(
                        id=_uuid7_hex(),
                        space_id=space_id,
                        created_by=None,
                        name=name,
                        amount=amount,
                        currency=currency,
                        billing_cycle=billing_cycle,
                        billing_day=billing_day,
                        category_id=category_id,
                        wallet_id=wallet_id,
                        payment_method=pm or None,
                        start_date=date.today(),
                        status=status,
                        notes=notes,
                        is_private=False,
                    )
                )
                migrated += 1

    logger.info("Subscriptions migrated", migrated=migrated, skipped=skipped)
    return migrated, skipped


# ======================== Balance Recalculation ========================


async def recalculate_wallet_balances(
    session_factory: async_sessionmaker,
    space_id: str,
    dry_run: bool,
) -> int:
    """Recalculate current_balance for all wallets based on completed transactions.

    current_balance = initial_balance + SUM(income) - SUM(expense)
    Returns the number of wallets updated.
    """
    if dry_run:
        return 0

    updated = 0

    async with session_factory() as db:
        async with db.begin():
            # Get all wallets in this space
            wallets = (
                await db.execute(
                    select(Wallet.id, Wallet.initial_balance).where(
                        Wallet.space_id == space_id,
                        Wallet.is_active.is_(True),
                    )
                )
            ).all()

            for wallet_id, initial_balance in wallets:
                # Sum income
                income_sum = (
                    await db.execute(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.wallet_id == wallet_id,
                            Transaction.type == "income",
                            Transaction.status == "completed",
                        )
                    )
                ).scalar_one()

                # Sum expense
                expense_sum = (
                    await db.execute(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.wallet_id == wallet_id,
                            Transaction.type == "expense",
                            Transaction.status == "completed",
                        )
                    )
                ).scalar_one()

                base = initial_balance or Decimal("0")
                new_balance = (
                    base + Decimal(str(income_sum)) - Decimal(str(expense_sum))
                )

                await db.execute(
                    text(
                        "UPDATE finance.wallets SET current_balance = :balance, "
                        "updated_at = NOW() WHERE id = :wid"
                    ).bindparams(balance=new_balance, wid=wallet_id)
                )
                updated += 1

    logger.info("Wallet balances recalculated", wallets_updated=updated)
    return updated


# ======================== Verification ========================


async def verify_migration(
    session_factory: async_sessionmaker,
    space_id: str,
) -> dict:
    """Compare V1 and V2 counts and sums for verification."""
    stats: dict = {}

    async with session_factory() as db:
        # V1 transaction count
        v1_tx_count = (
            await db.execute(text("SELECT COUNT(*) FROM pulso_finance.transactions"))
        ).scalar_one()

        # V1 transaction sum by type
        v1_income_sum = (
            await db.execute(
                text(
                    "SELECT COALESCE(SUM(amount), 0) FROM pulso_finance.transactions "
                    "WHERE type = 'income'"
                )
            )
        ).scalar_one()

        v1_expense_sum = (
            await db.execute(
                text(
                    "SELECT COALESCE(SUM(amount), 0) FROM pulso_finance.transactions "
                    "WHERE type = 'expense'"
                )
            )
        ).scalar_one()

        # V1 subscription count
        v1_sub_count = (
            await db.execute(text("SELECT COUNT(*) FROM pulso_finance.subscriptions"))
        ).scalar_one()

        # V2 transaction count (only v1-migrated ones)
        v2_tx_count = (
            await db.execute(
                select(func.count()).select_from(Transaction).where(
                    Transaction.space_id == space_id,
                    Transaction.invoice_number.like("v1:%"),
                )
            )
        ).scalar_one()

        # V2 transaction sums (only v1-migrated)
        v2_income_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.space_id == space_id,
                    Transaction.invoice_number.like("v1:%"),
                    Transaction.type == "income",
                )
            )
        ).scalar_one()

        v2_expense_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.space_id == space_id,
                    Transaction.invoice_number.like("v1:%"),
                    Transaction.type == "expense",
                )
            )
        ).scalar_one()

        # V2 subscription count
        v2_sub_count = (
            await db.execute(
                select(func.count()).select_from(Subscription).where(
                    Subscription.space_id == space_id,
                )
            )
        ).scalar_one()

        # V2 wallet count
        v2_wallet_count = (
            await db.execute(
                select(func.count()).select_from(Wallet).where(
                    Wallet.space_id == space_id,
                    Wallet.is_active.is_(True),
                )
            )
        ).scalar_one()

        # V2 category count
        v2_cat_count = (
            await db.execute(
                select(func.count()).select_from(Category).where(
                    Category.space_id == space_id,
                    Category.is_active.is_(True),
                )
            )
        ).scalar_one()

        # V1 unique categories for coverage calc
        v1_unique_cats = (
            await db.execute(
                text(
                    "SELECT COUNT(DISTINCT category) FROM pulso_finance.transactions "
                    "WHERE category IS NOT NULL AND category != ''"
                )
            )
        ).scalar_one()

    stats = {
        "v1_tx_count": v1_tx_count,
        "v1_income_sum": Decimal(str(v1_income_sum)),
        "v1_expense_sum": Decimal(str(v1_expense_sum)),
        "v1_sub_count": v1_sub_count,
        "v1_unique_categories": v1_unique_cats,
        "v2_tx_count": v2_tx_count,
        "v2_income_sum": Decimal(str(v2_income_sum)),
        "v2_expense_sum": Decimal(str(v2_expense_sum)),
        "v2_sub_count": v2_sub_count,
        "v2_wallet_count": v2_wallet_count,
        "v2_cat_count": v2_cat_count,
    }
    return stats


def print_summary(stats: dict, dry_run: bool) -> None:
    """Print a formatted verification summary table."""
    mode_label = "[DRY RUN] " if dry_run else ""
    sep = "=" * 60

    v1_total_sum = stats["v1_income_sum"] + stats["v1_expense_sum"]
    v2_total_sum = stats["v2_income_sum"] + stats["v2_expense_sum"]

    # Category coverage: V2 categories (minus default) / V1 unique categories
    v1_cats = stats["v1_unique_categories"]
    v2_cats_real = max(stats["v2_cat_count"] - 1, 0)  # exclude default
    cat_coverage = (v2_cats_real / v1_cats * 100) if v1_cats > 0 else 100.0

    tx_match = stats["v1_tx_count"] == stats["v2_tx_count"]
    sum_match = v1_total_sum == v2_total_sum

    print(f"\n{sep}")
    print(f"  {mode_label}MIGRATION VERIFICATION SUMMARY")
    print(sep)
    print(f"  {'Metric':<30} {'V1':>12} {'V2':>12} {'Match':>8}")
    print(f"  {'-' * 30} {'-' * 12} {'-' * 12} {'-' * 8}")
    print(
        f"  {'Transaction count':<30} {stats['v1_tx_count']:>12} "
        f"{stats['v2_tx_count']:>12} {'OK' if tx_match else 'MISMATCH':>8}"
    )
    inc_ok = stats["v1_income_sum"] == stats["v2_income_sum"]
    exp_ok = stats["v1_expense_sum"] == stats["v2_expense_sum"]
    sub_ok = stats["v1_sub_count"] == stats["v2_sub_count"]
    _m = lambda ok: "OK" if ok else "MISMATCH"  # noqa: E731
    print(
        f"  {'Income sum':<30} {stats['v1_income_sum']:>12.4f} "
        f"{stats['v2_income_sum']:>12.4f} {_m(inc_ok):>8}"
    )
    print(
        f"  {'Expense sum':<30} {stats['v1_expense_sum']:>12.4f} "
        f"{stats['v2_expense_sum']:>12.4f} {_m(exp_ok):>8}"
    )
    print(
        f"  {'Total sum':<30} {v1_total_sum:>12.4f} "
        f"{v2_total_sum:>12.4f} {_m(sum_match):>8}"
    )
    print(
        f"  {'Subscription count':<30} {stats['v1_sub_count']:>12} "
        f"{stats['v2_sub_count']:>12} {_m(sub_ok):>8}"
    )
    print(f"  {'-' * 30} {'-' * 12} {'-' * 12} {'-' * 8}")
    print(f"  {'Wallets created':<30} {'':>12} {stats['v2_wallet_count']:>12}")
    print(f"  {'Categories created':<30} {'':>12} {stats['v2_cat_count']:>12}")
    print(f"  {'Category coverage':<30} {'':>12} {cat_coverage:>11.1f}%")
    print(sep)

    if tx_match and sum_match:
        print("  Result: ALL CHECKS PASSED")
    else:
        print("  Result: MISMATCH DETECTED -- review logs above")
    print(f"{sep}\n")


# ======================== Main ========================


async def main(
    space_id: str,
    db_url: str,
    dry_run: bool,
) -> None:
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    mode_str = "DRY RUN" if dry_run else "LIVE"
    logger.info(
        "Starting V1 finance migration",
        mode=mode_str,
        space_id=space_id,
        db_url=db_url.split("@")[-1],  # hide credentials in log
    )

    # -- 1. Read all V1 data ------------------------------------------------
    v1_transactions = await read_v1_transactions(session_factory)
    v1_tag_map = await read_v1_transaction_tags(session_factory)
    v1_subscriptions = await read_v1_subscriptions(session_factory)
    _v1_sub_tag_map = await read_v1_subscription_tags(session_factory)

    if not v1_transactions and not v1_subscriptions:
        logger.warning("No V1 data found in pulso_finance schema. Nothing to migrate.")
        await engine.dispose()
        return

    # -- 2. Build inference maps -------------------------------------------
    wallet_map = build_wallet_map(v1_transactions, v1_subscriptions, space_id)
    cat_map = build_category_map(v1_transactions, v1_subscriptions, space_id)

    # -- 3. Create wallets and categories ----------------------------------
    wallets_created, wallets_skipped = await create_wallets(
        session_factory, wallet_map, space_id, dry_run
    )
    cats_created, cats_skipped = await create_categories(
        session_factory, cat_map, space_id, dry_run
    )

    # -- 4. Migrate transactions -------------------------------------------
    tx_migrated, tx_skipped = await migrate_transactions(
        session_factory, v1_transactions, v1_tag_map,
        wallet_map, cat_map, space_id, dry_run,
    )

    # -- 5. Migrate subscriptions ------------------------------------------
    sub_migrated, sub_skipped = await migrate_subscriptions(
        session_factory, v1_subscriptions,
        wallet_map, cat_map, space_id, dry_run,
    )

    # -- 6. Recalculate wallet balances ------------------------------------
    wallets_updated = await recalculate_wallet_balances(session_factory, space_id, dry_run)

    # -- 7. Verification ---------------------------------------------------
    if not dry_run:
        stats = await verify_migration(session_factory, space_id)
        print_summary(stats, dry_run=False)
    else:
        # In dry-run, still read V1 counts for the summary
        stats = await verify_migration(session_factory, space_id)
        # Override V2 counts with what we would have created
        stats["v2_tx_count"] = tx_migrated + tx_skipped  # skipped = already in V2
        stats["v2_sub_count"] = sub_migrated + sub_skipped
        stats["v2_wallet_count"] = wallets_created
        stats["v2_cat_count"] = cats_created
        print_summary(stats, dry_run=True)

    # -- Summary log -------------------------------------------------------
    logger.info(
        "Migration complete",
        mode=mode_str,
        wallets_created=wallets_created,
        wallets_skipped=wallets_skipped,
        categories_created=cats_created,
        categories_skipped=cats_skipped,
        transactions_migrated=tx_migrated,
        transactions_skipped=tx_skipped,
        subscriptions_migrated=sub_migrated,
        subscriptions_skipped=sub_skipped,
        wallets_balance_updated=wallets_updated,
    )

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate V1 finance data (pulso_finance) to V2 (finance schema)"
    )
    parser.add_argument(
        "--space-id",
        required=True,
        help="Target space ID for all V2 records",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"PostgreSQL asyncpg connection URL (default: {DEFAULT_DB_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read V1 data and log stats without writing to V2",
    )
    args = parser.parse_args()
    asyncio.run(main(args.space_id, args.db_url, args.dry_run))
