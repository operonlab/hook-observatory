"""FinanceGRCAdapter — Reflect-only G-R-C adapter for transaction quality metrics.

Implements SupportsReflect to analyze transaction categorization coverage,
description completeness, and category/type distribution over the past 30 days.

gather_items() is sync per the Protocol definition. The route layer calls
adapter.fetch_blocks(db, space_id) first (awaited), then passes the result as
blocks= kwarg to gather_items(). grc_routes.py detects fetch_blocks via hasattr().
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.grc import GenerateItem, ReflectResult

LOOKBACK_DAYS = 30
TOP_CATEGORY_COUNT = 5


class FinanceGRCAdapter:
    """Reflect-only adapter — transaction categorization and completeness metrics.

    Phase 1: Reflect only (no Curate).
    Implements SupportsReflect Protocol from src.shared.grc.

    The fetch_blocks() async method is called by grc_routes.py before
    gather_items() to pre-fetch DB data in an async context.
    """

    # ── Async pre-fetch hook (detected by grc_routes via hasattr) ─────

    async def fetch_blocks(self, db: AsyncSession, space_id: str) -> list[dict[str, Any]]:
        """Fetch recent transactions + category names for this space (last 30 days).

        Returns list of dicts with keys:
          id, type, amount, description, merchant, category_id,
          category_name, created_at.
        """
        from src.modules.finance.models import Category, Transaction

        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)

        stmt = select(Transaction).where(
            Transaction.space_id == space_id,
            Transaction.transacted_at >= cutoff,
            Transaction.deleted_at.is_(None),
        )
        txns = list((await db.execute(stmt)).scalars().all())
        if not txns:
            return []

        # Batch-load categories for display names
        cat_ids = {t.category_id for t in txns if t.category_id}
        category_names: dict[str, str] = {}
        if cat_ids:
            cat_stmt = select(Category.id, Category.name).where(Category.id.in_(cat_ids))
            for row in (await db.execute(cat_stmt)).all():
                category_names[row.id] = row.name

        return [
            {
                "id": t.id,
                "type": t.type,
                "amount": str(t.amount),
                "description": t.description,
                "merchant": t.merchant,
                "category_id": t.category_id,
                "category_name": category_names.get(t.category_id, None) if t.category_id else None,
                "created_at": t.transacted_at.isoformat() if t.transacted_at else None,
            }
            for t in txns
        ]

    # ── SupportsReflect ────────────────────────────────────────────────

    def gather_items(self, scope_id: str, **kwargs: Any) -> list[GenerateItem]:
        """Convert pre-fetched blocks into GenerateItems.

        Caller MUST pass blocks=list[dict] via kwargs (pre-fetched by fetch_blocks()).
        If blocks is absent, returns empty list — no DB access here.
        """
        blocks: list[dict[str, Any]] = kwargs.get("blocks", [])
        return [
            GenerateItem(
                id=b["id"],
                content=b.get("description") or b.get("merchant") or "",
                metadata={
                    "type": b.get("type", "expense"),
                    "amount": b.get("amount", 0.0),
                    "category_id": b.get("category_id"),
                    "category_name": b.get("category_name"),
                    "has_description": bool(b.get("description")),
                    "merchant": b.get("merchant"),
                    "created_at": b.get("created_at"),
                },
            )
            for b in blocks
        ]

    def reflect(self, items: list[GenerateItem], scope_id: str) -> ReflectResult:
        """Compute transaction categorization and completeness metrics.

        Metrics written to result.metrics:
          - total_transactions: count of transactions analyzed
          - categorized_pct: % with non-null category_id
          - described_pct: % with non-null description
          - type_income_count / type_expense_count / type_transfer_count
          - top_category_{name}: transaction count for top 5 categories
        """
        result = ReflectResult(
            module="finance",
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        if not items:
            result.insights.append(f"No transactions in the last {LOOKBACK_DAYS} days.")
            return result

        total = len(items)

        # Categorization coverage
        categorized = [it for it in items if it.metadata.get("category_id")]
        categorized_pct = len(categorized) / total * 100

        # Description coverage
        described = [it for it in items if it.metadata.get("has_description")]
        described_pct = len(described) / total * 100

        # Type distribution
        type_counts: dict[str, int] = defaultdict(int)
        for it in items:
            type_counts[it.metadata.get("type", "expense")] += 1

        # Category distribution — top N by count
        cat_counter: Counter[str] = Counter()
        for it in items:
            name = it.metadata.get("category_name")
            if name:
                cat_counter[name] += 1
        top_cats = cat_counter.most_common(TOP_CATEGORY_COUNT)

        # Populate metrics
        result.metrics = {
            "total_transactions": float(total),
            "categorized_pct": round(categorized_pct, 1),
            "described_pct": round(described_pct, 1),
            "type_income_count": float(type_counts.get("income", 0)),
            "type_expense_count": float(type_counts.get("expense", 0)),
            "type_transfer_count": float(type_counts.get("transfer", 0)),
            **{f"top_category_{name}": float(cnt) for name, cnt in top_cats},
        }

        # Insights
        result.insights.append(
            f"{categorized_pct:.0f}% transactions categorized "
            f"({len(categorized)}/{total}, last {LOOKBACK_DAYS}d)"
        )
        result.insights.append(
            f"{described_pct:.0f}% transactions have a description ({len(described)}/{total})"
        )
        if top_cats:
            top_name, top_cnt = top_cats[0]
            result.insights.append(
                f"Category '{top_name}' has highest volume: {top_cnt} transactions"
            )
        type_summary = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
        result.insights.append(f"Type distribution: {type_summary}")

        # Anomaly: uncategorized transactions
        uncategorized_count = total - len(categorized)
        if uncategorized_count > 0:
            result.anomalies.append(
                f"Uncategorized transactions: {uncategorized_count} "
                f"({100 - categorized_pct:.0f}% of total)"
            )

        # Anomaly: description coverage critically low
        if described_pct < 20:
            result.anomalies.append(
                f"Low description coverage: only {described_pct:.0f}% transactions "
                "have a description — harder to audit"
            )

        return result
