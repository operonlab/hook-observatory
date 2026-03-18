"""Finance monthly report generator — comprehensive financial overview.

Aggregates transactions, wallets, categories, budgets, installments,
and subscriptions into a single report dict suitable for JSON serialization.

All monetary values are returned as str (from Decimal) for JSON safety.
"""

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Budget,
    Category,
    InstallmentPlan,
    Subscription,
    Transaction,
    Wallet,
)
from .services import apply_privacy_filter

logger = structlog.get_logger()


def _dec(value: Decimal | None) -> str:
    """Convert Decimal to str for JSON serialization, defaulting to '0.0000'."""
    if value is None:
        return "0.0000"
    return str(value)


def _pct_change(current: Decimal, previous: Decimal) -> float | None:
    """Calculate percentage change from previous to current.

    Returns None if previous is zero (division undefined).
    """
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


async def _income_expense_for_month(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None,
) -> dict:
    """Aggregate income, expense, and transaction count for a single month.

    Returns a dict with total_income, total_expense, net, transaction_count
    (all as Decimal) or None if no transactions exist.
    """
    q = (
        select(
            Transaction.type,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            func.count().label("cnt"),
        )
        .where(
            Transaction.space_id == space_id,
            Transaction.status == "completed",
            func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
        )
        .group_by(Transaction.type)
    )
    q = apply_privacy_filter(q, Transaction, viewer_id)
    rows = (await db.execute(q)).all()

    if not rows:
        return None

    income = Decimal("0")
    expense = Decimal("0")
    count = 0
    for row in rows:
        if row.type == "income":
            income = row.total or Decimal("0")
        elif row.type == "expense":
            expense = row.total or Decimal("0")
        count += row.cnt

    return {
        "total_income": income,
        "total_expense": expense,
        "net": income - expense,
        "transaction_count": count,
    }


def _prev_year_month(year_month: str) -> str:
    """Return the previous month in 'YYYY-MM' format.

    E.g. '2026-03' -> '2026-02', '2026-01' -> '2025-12'.
    """
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


async def _build_income_expense_section(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None,
) -> dict:
    """Build the income/expense summary section with month-over-month comparison."""
    current = await _income_expense_for_month(db, space_id, year_month, viewer_id)
    if current is None:
        current = {
            "total_income": Decimal("0"),
            "total_expense": Decimal("0"),
            "net": Decimal("0"),
            "transaction_count": 0,
        }

    prev_ym = _prev_year_month(year_month)
    prev = await _income_expense_for_month(db, space_id, prev_ym, viewer_id)

    income_change_pct = None
    expense_change_pct = None
    prev_serialized = None
    if prev is not None:
        income_change_pct = _pct_change(current["total_income"], prev["total_income"])
        expense_change_pct = _pct_change(current["total_expense"], prev["total_expense"])
        prev_serialized = {
            "total_income": _dec(prev["total_income"]),
            "total_expense": _dec(prev["total_expense"]),
            "net": _dec(prev["net"]),
            "transaction_count": prev["transaction_count"],
        }

    return {
        "total_income": _dec(current["total_income"]),
        "total_expense": _dec(current["total_expense"]),
        "net": _dec(current["net"]),
        "transaction_count": current["transaction_count"],
        "prev_month": prev_serialized,
        "income_change_pct": income_change_pct,
        "expense_change_pct": expense_change_pct,
    }


async def _build_wallets_section(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None,
) -> dict:
    """Build the wallet overview section.

    For each active wallet: name, current_balance, month income/expense/net.
    Also calculates total net worth across all wallets.
    """
    # Fetch active wallets
    wallets_q = select(Wallet).where(
        Wallet.space_id == space_id,
        Wallet.is_active == True,  # noqa: E712
    )
    wallets_q = apply_privacy_filter(wallets_q, Wallet, viewer_id)
    wallets_q = wallets_q.order_by(Wallet.sort_order, Wallet.name)
    wallets = (await db.execute(wallets_q)).scalars().all()

    if not wallets:
        return {"items": [], "total_net_worth": "0.0000"}

    wallet_ids = [w.id for w in wallets]

    # Per-wallet income for this month
    income_q = (
        select(
            Transaction.wallet_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .where(
            Transaction.wallet_id.in_(wallet_ids),
            Transaction.type == "income",
            Transaction.status == "completed",
            func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
        )
        .group_by(Transaction.wallet_id)
    )
    income_q = apply_privacy_filter(income_q, Transaction, viewer_id)
    income_rows = (await db.execute(income_q)).all()
    income_map = {row.wallet_id: row.total for row in income_rows}

    # Per-wallet expense for this month
    expense_q = (
        select(
            Transaction.wallet_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .where(
            Transaction.wallet_id.in_(wallet_ids),
            Transaction.type == "expense",
            Transaction.status == "completed",
            func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
        )
        .group_by(Transaction.wallet_id)
    )
    expense_q = apply_privacy_filter(expense_q, Transaction, viewer_id)
    expense_rows = (await db.execute(expense_q)).all()
    expense_map = {row.wallet_id: row.total for row in expense_rows}

    total_net_worth = Decimal("0")
    items = []
    for w in wallets:
        w_income = income_map.get(w.id, Decimal("0"))
        w_expense = expense_map.get(w.id, Decimal("0"))
        w_net = w_income - w_expense
        total_net_worth += w.current_balance
        items.append(
            {
                "wallet_id": w.id,
                "name": w.name,
                "type": w.type,
                "currency": w.currency,
                "current_balance": _dec(w.current_balance),
                "month_income": _dec(w_income),
                "month_expense": _dec(w_expense),
                "month_net_change": _dec(w_net),
            }
        )

    return {
        "items": items,
        "total_net_worth": _dec(total_net_worth),
    }


async def _build_categories_section(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None,
) -> list[dict]:
    """Build the category analysis section (expense breakdown with budget comparison).

    Each category includes: name, total, count, percentage, and budget info if available.
    Sorted by amount DESC.
    """
    # Expense by category
    cat_q = (
        select(
            Transaction.category_id,
            func.coalesce(Category.name, "未分類").label("category_name"),
            func.sum(Transaction.amount).label("total"),
            func.count().label("cnt"),
        )
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.space_id == space_id,
            Transaction.type == "expense",
            Transaction.status == "completed",
            func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
        )
        .group_by(Transaction.category_id, Category.name)
        .order_by(func.sum(Transaction.amount).desc())
    )
    cat_q = apply_privacy_filter(cat_q, Transaction, viewer_id)
    cat_rows = (await db.execute(cat_q)).all()

    if not cat_rows:
        return []

    # Total expense for percentage calculation
    total_expense = sum(row.total for row in cat_rows)

    # Load budgets for this month
    budget_q = select(Budget).where(
        Budget.space_id == space_id,
        Budget.year_month == year_month,
        Budget.category_id != None,  # noqa: E711 — only per-category budgets
    )
    budget_q = apply_privacy_filter(budget_q, Budget, viewer_id)
    budgets = (await db.execute(budget_q)).scalars().all()
    budget_map = {b.category_id: b for b in budgets}

    items = []
    for row in cat_rows:
        pct = float(row.total / total_expense * 100) if total_expense else 0.0
        entry = {
            "category_id": row.category_id,
            "category_name": row.category_name,
            "total_amount": _dec(row.total),
            "count": row.cnt,
            "percentage": round(pct, 1),
            "budget": None,
        }

        budget = budget_map.get(row.category_id)
        if budget:
            remaining = budget.budget_amount - row.total
            entry["budget"] = {
                "budget_amount": _dec(budget.budget_amount),
                "remaining": _dec(remaining),
                "exceeded": row.total > budget.budget_amount,
            }

        items.append(entry)

    return items


async def _build_installments_section(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None,
) -> dict:
    """Build the installment tracking section.

    Lists active plans with progress and counts transactions due this month.
    """
    # Active installment plans
    plans_q = select(InstallmentPlan).where(
        InstallmentPlan.space_id == space_id,
        InstallmentPlan.status == "active",
    )
    plans_q = apply_privacy_filter(plans_q, InstallmentPlan, viewer_id)
    plans_q = plans_q.order_by(InstallmentPlan.start_date.desc())
    plans = (await db.execute(plans_q)).scalars().all()

    items = []
    for plan in plans:
        # Count completed installments
        completed_q = select(func.count()).where(
            Transaction.installment_plan_id == plan.id,
            Transaction.status == "completed",
        )
        completed_count = (await db.execute(completed_q)).scalar_one()

        remaining_total = plan.installment_amount * (plan.num_installments - completed_count)
        items.append(
            {
                "plan_id": plan.id,
                "description": plan.description,
                "merchant": plan.merchant,
                "current_period": completed_count,
                "total_periods": plan.num_installments,
                "installment_amount": _dec(plan.installment_amount),
                "remaining_total": _dec(max(remaining_total, Decimal("0"))),
                "wallet_id": plan.wallet_id,
            }
        )

    # Scheduled installment transactions due this month
    due_q = select(func.count()).where(
        Transaction.space_id == space_id,
        Transaction.status == "scheduled",
        Transaction.installment_plan_id != None,  # noqa: E711
        func.to_char(Transaction.transacted_at, "YYYY-MM") == year_month,
    )
    due_this_month = (await db.execute(due_q)).scalar_one()

    return {
        "items": items,
        "due_this_month": due_this_month,
    }


async def _build_subscriptions_section(
    db: AsyncSession,
    space_id: str,
    viewer_id: str | None,
) -> dict:
    """Build the subscription summary section.

    Lists active subscriptions and calculates total monthly cost
    (yearly subscriptions are divided by 12, weekly multiplied by ~4.33).
    """
    subs_q = select(Subscription).where(
        Subscription.space_id == space_id,
        Subscription.status == "active",
    )
    subs_q = apply_privacy_filter(subs_q, Subscription, viewer_id)
    subs_q = subs_q.order_by(Subscription.amount.desc())
    subs = (await db.execute(subs_q)).scalars().all()

    total_monthly = Decimal("0")
    items = []
    for s in subs:
        # Normalize to monthly cost
        if s.billing_cycle == "yearly":
            monthly_equiv = s.amount / 12
        elif s.billing_cycle == "weekly":
            monthly_equiv = s.amount * Decimal("4.3333")
        else:  # monthly
            monthly_equiv = s.amount

        total_monthly += monthly_equiv

        items.append(
            {
                "subscription_id": s.id,
                "name": s.name,
                "amount": _dec(s.amount),
                "currency": s.currency,
                "billing_cycle": s.billing_cycle,
                "next_billing": s.next_billing.isoformat() if s.next_billing else None,
                "category_id": s.category_id,
                "wallet_id": s.wallet_id,
                "monthly_equivalent": _dec(monthly_equiv),
            }
        )

    return {
        "items": items,
        "total_monthly_cost": _dec(total_monthly),
    }


async def generate_monthly_report(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None = None,
) -> dict:
    """Generate a comprehensive monthly financial report.

    Aggregates data from transactions, wallets, categories, budgets,
    installment plans, and subscriptions into a single report dict.

    Args:
        db: Async database session.
        space_id: The space to generate the report for.
        year_month: Target month in 'YYYY-MM' format (e.g. '2026-03').
        viewer_id: Current user ID for privacy filtering. If None,
            only public records are included.

    Returns:
        A plain dict with all report sections. Monetary values are
        serialized as str for JSON safety.
    """
    logger.info(
        "generating_monthly_report",
        space_id=space_id,
        year_month=year_month,
    )

    # Build all sections concurrently-safe (sequential to share session)
    income_expense = await _build_income_expense_section(db, space_id, year_month, viewer_id)
    wallets = await _build_wallets_section(db, space_id, year_month, viewer_id)
    categories = await _build_categories_section(db, space_id, year_month, viewer_id)
    installments = await _build_installments_section(db, space_id, year_month, viewer_id)
    subscriptions = await _build_subscriptions_section(db, space_id, viewer_id)

    # AI suggestions placeholder
    # TODO: Integrate oMLX for spending pattern analysis
    # Expected flow: embed category vectors -> cluster -> generate natural-language advice
    ai_suggestions = ["AI 建議功能開發中"]

    report = {
        "year_month": year_month,
        "generated_at": datetime.now(UTC).isoformat(),
        "income_expense": income_expense,
        "wallets": wallets,
        "categories": categories,
        "installments": installments,
        "subscriptions": subscriptions,
        "ai_suggestions": ai_suggestions,
    }

    logger.info(
        "monthly_report_generated",
        space_id=space_id,
        year_month=year_month,
        transaction_count=income_expense["transaction_count"],
        wallet_count=len(wallets.get("items", [])),
        category_count=len(categories),
    )

    return report


# ── RLM-powered Monthly Insights ─────────────────────────────────────────────


async def generate_monthly_insights_rlm(
    db: AsyncSession,
    space_id: str,
    year_month: str,
    viewer_id: str | None = None,
) -> dict:
    """Generate AI-powered monthly financial insights using RLM engine.

    Performs recursive trend analysis, anomaly detection, and generates
    a natural language narrative report with recommendations.

    Falls back to a basic summary dict on any RLM failure.

    Args:
        db: Async database session.
        space_id: The space to analyze.
        year_month: Target month in 'YYYY-MM' format.
        viewer_id: Current user ID for privacy filtering.

    Returns:
        Dict with keys: trends, anomalies, narrative, recommendations, metadata.
    """
    import json as _json

    from src.shared.rlm_engine import RLMConfig, RLMEngine

    logger.info("generating_monthly_insights_rlm", space_id=space_id, year_month=year_month)

    # Gather raw report data as context for RLM
    report = await generate_monthly_report(db, space_id, year_month, viewer_id)

    # Also fetch previous 3 months for trend analysis
    prev_months_data: list[dict] = []
    ym = year_month
    for _ in range(3):
        ym = _prev_year_month(ym)
        prev_ie = await _income_expense_for_month(db, space_id, ym, viewer_id)
        if prev_ie:
            prev_months_data.append(
                {
                    "year_month": ym,
                    "total_income": _dec(prev_ie["total_income"]),
                    "total_expense": _dec(prev_ie["total_expense"]),
                    "net": _dec(prev_ie["net"]),
                    "transaction_count": prev_ie["transaction_count"],
                }
            )

    context_data = {
        "current_report": report,
        "historical_months": prev_months_data,
    }
    context_str = _json.dumps(context_data, ensure_ascii=False, indent=2, default=str)

    prompt = (
        f"分析 {year_month} 的月度財務數據，提供以下四個部分的深度洞察：\n\n"
        "1. **trends**: 分析各分類的消費趨勢（與前幾月比較），找出增減明顯的分類\n"
        "2. **anomalies**: 偵測異常消費（單筆大額、分類支出激增、預算超支等）\n"
        "3. **narrative**: 用自然語言撰寫一段完整的月度財務敘述報告（繁體中文）\n"
        "4. **recommendations**: 提供具體、可執行的理財建議\n\n"
        "以 JSON 格式回覆：\n"
        '{"trends": [...], "anomalies": [...], "narrative": "...", "recommendations": [...]}\n\n'
        "FINAL() 包住你的 JSON 結果。"
    )

    config = RLMConfig(
        model="grok-4-fast",
        sub_model="haiku",
        max_iterations=5,
        max_timeout_secs=60.0,
        api_base="http://localhost:4000/v1",
        api_key="sk-litellm-local-dev",
        max_depth=2,
    )
    engine = RLMEngine(config)

    fallback = {
        "trends": [],
        "anomalies": [],
        "narrative": f"{year_month} 月度財務洞察生成失敗，請查看基礎報告。",
        "recommendations": [],
        "metadata": {"status": "fallback", "year_month": year_month},
    }

    try:
        result = engine.completion(prompt=prompt, context=context_str)

        if result.status != "ok":
            logger.warning(
                "rlm_insights_non_ok",
                status=result.status,
                iterations=result.iterations,
            )
            fallback["metadata"]["rlm_status"] = result.status
            return fallback

        # Parse RLM response as JSON
        import re as _re

        raw = result.response
        # Strip markdown code fences if present
        raw = _re.sub(r"```(?:json)?\s*", "", raw)
        raw = _re.sub(r"```\s*", "", raw)

        match = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not match:
            logger.warning("rlm_insights_no_json", raw_preview=raw[:300])
            fallback["metadata"]["raw_response"] = raw[:500]
            return fallback

        insights = _json.loads(match.group())

        result_dict = {
            "trends": insights.get("trends", []),
            "anomalies": insights.get("anomalies", []),
            "narrative": insights.get("narrative", ""),
            "recommendations": insights.get("recommendations", []),
            "metadata": {
                "status": "ok",
                "year_month": year_month,
                "rlm_iterations": result.iterations,
                "rlm_time_secs": round(result.execution_time_secs, 2),
                "rlm_calls": result.usage.total_calls,
            },
        }

        logger.info(
            "monthly_insights_rlm_generated",
            space_id=space_id,
            year_month=year_month,
            iterations=result.iterations,
            time_secs=round(result.execution_time_secs, 2),
        )
        return result_dict

    except Exception:
        logger.exception("rlm_insights_error", space_id=space_id, year_month=year_month)
        return fallback
