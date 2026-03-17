#!/usr/bin/env python3
"""Finance Analytics MCP Server — analytics + budget thin adapter over Core API.

9 tools: summary, insights, budget, reports, breakdowns, forecasts, export.

Usage:
    python3 mcp/finance-analytics/server.py

Configure in ~/.claude.json:
    "workshop-finance-analytics": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/finance-analytics/server.py"],
        "env": {}
    }
"""

import json
from asyncio import to_thread
from typing import Any

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.finance import FinanceClient

mcp = FastMCP("workshop-finance-analytics")
client = FinanceClient()


# ======================== Helpers ========================


def fmt_amount(amount: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(amount):,.0f}"


def pct(value: float, total: float) -> str:
    if total == 0:
        return "0%"
    return f"{value / total * 100:.0f}%"


# ======================== Tool Implementations ========================


@mcp.tool()
async def finance_summary(month: str | None = None) -> str:
    """月度收支摘要（含分類明細、錢包餘額總覽、淨資產）"""
    try:
        result = await to_thread(client.get_summary, month=month)

        display_month = result.get("month", month or "current")
        income = float(result.get("total_income", 0))
        expense = float(result.get("total_expense", 0))
        net = income - expense

        lines = [
            f"# Finance Summary — {display_month}\n",
            f"Income:  {fmt_amount(income)}",
            f"Expense: {fmt_amount(expense)}",
            f"Net:     {fmt_amount(net)}",
        ]

        categories = result.get("categories", [])
        if categories:
            lines.append("\n## By Category")
            for c in categories:
                lines.append(f"  {c.get('icon', '')} {c['name']}: {fmt_amount(c['amount'])}")

        wallets = result.get("wallets", [])
        if wallets:
            lines.append("\n## Wallet Balances")
            for w in wallets:
                lines.append(f"  {w['name']}: {fmt_amount(w.get('current_balance', 0))}")
            net_worth = sum(float(w.get("current_balance", 0)) for w in wallets)
            lines.append(f"\n  Net worth: {fmt_amount(net_worth)}")

        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_insights(months: int = 6) -> str:
    """多月消費趨勢分析（近 N 月收支走勢、異常偵測）"""
    try:
        result = await to_thread(client.monthly_trends, months=months)

        trends = result.get("trends", []) if isinstance(result, dict) else result
        if not trends:
            return "No trend data available."

        lines = [f"# Spending Insights (past {months} months)\n"]

        lines.append("## Monthly Trend")
        for t in trends:
            bar_len = min(30, int(float(t.get("expense", 0)) / 1000))
            bar = "█" * bar_len
            lines.append(
                f"  {t['month']}  income: {fmt_amount(t.get('income', 0)):>12s}  "
                f"expense: {fmt_amount(t.get('expense', 0)):>12s}  {bar}"
            )

        anomalies = result.get("anomalies", []) if isinstance(result, dict) else []
        if anomalies:
            lines.append("\n## Anomalies")
            for a in anomalies:
                lines.append(f"  ⚠️ {a.get('description', a)}")

        cat_trends = result.get("category_trends", []) if isinstance(result, dict) else []
        if cat_trends:
            lines.append("\n## Category Trends")
            for c in cat_trends:
                direction = "↑" if c.get("trend", 0) > 0 else "↓" if c.get("trend", 0) < 0 else "→"
                lines.append(f"  {c['name']}: {direction} {c.get('trend_pct', 0):+.0f}%")

        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_budget_set(
    year_month: str,
    budget_amount: float,
    savings_target: float | None = None,
    category_budgets: list = None,
) -> str:
    """設定月度預算（總額 + 分類）"""
    try:
        body: dict[str, Any] = {
            "year_month": year_month,
            "budget_amount": budget_amount,
        }
        if savings_target is not None:
            body["savings_target"] = savings_target
        if category_budgets is not None:
            body["category_budgets"] = category_budgets

        await to_thread(client.upsert_budget, body)

        lines = [
            f"Budget set for {year_month}.\n",
            f"Total budget: {fmt_amount(budget_amount)}",
        ]
        if savings_target is not None:
            lines.append(f"Savings target: {fmt_amount(savings_target)}")

        cats = category_budgets or []
        if cats:
            lines.append(f"\nCategory budgets: {len(cats)} set")
            for c in cats:
                lines.append(f"  - {c['category_id'][:8]}: {fmt_amount(c['amount'])}")

        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_budget_status(year_month: str | None = None) -> str:
    """查詢預算消耗狀態（含承諾支出 vs 自由支出）"""
    try:
        result = await to_thread(client.list_budgets, year_month=year_month)

        month = result.get("year_month", year_month or "current")
        budget = float(result.get("budget_amount", 0))
        spent = float(result.get("total_spent", 0))
        committed = float(result.get("committed_expense", 0))
        free = budget - spent - committed
        remaining = budget - spent

        lines = [
            f"# Budget Status — {month}\n",
            f"Budget:    {fmt_amount(budget)}",
            f"Spent:     {fmt_amount(spent)} ({pct(spent, budget)})",
            f"Committed: {fmt_amount(committed)} (installments + subscriptions)",
            f"Free:      {fmt_amount(max(0, free))}",
            f"Remaining: {fmt_amount(remaining)}",
        ]

        if budget > 0 and spent > budget:
            lines.append(f"\n⚠️ Over budget by {fmt_amount(spent - budget)}")

        savings = result.get("savings_target")
        if savings:
            income = float(result.get("total_income", 0))
            actual_savings = income - spent
            lines.append(f"\nSavings target: {fmt_amount(float(savings))}")
            lines.append(f"Actual savings: {fmt_amount(actual_savings)}")

        categories = result.get("categories", [])
        if categories:
            lines.append("\n## Category Budgets")
            for c in categories:
                cat_budget = float(c.get("budget_amount", 0))
                cat_spent = float(c.get("spent", 0))
                status = "✅" if cat_spent <= cat_budget else "⚠️"
                lines.append(
                    f"  {status} {c['name']}: {fmt_amount(cat_spent)} / {fmt_amount(cat_budget)} "
                    f"({pct(cat_spent, cat_budget)})"
                )

        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_monthly_report(year_month: str, regenerate: bool = False) -> str:
    """產生或查閱月度消費報告（含 AI 建議）"""
    try:
        if regenerate:
            result = await to_thread(client.generate_monthly_report, year_month, regenerate=True)
        else:
            result = await to_thread(client.get_monthly_report, year_month)

        report = result.get("report") or result.get("content", "")
        if not report:
            return f"No report available for {year_month}. Use regenerate=true to generate one."

        return f"# Monthly Report — {year_month}\n\n{report}"
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_category_breakdown(month: str | None = None, category_id: str | None = None) -> str:
    """分類消費明細（含子分類展開）"""
    try:
        result = await to_thread(client.get_category_breakdown, month=month, category_id=category_id)
        items = result if isinstance(result, list) else result.get("items", [])

        if not items:
            return "No category data found."

        total = sum(float(c.get("amount", 0)) for c in items)
        lines = [f"# Category Breakdown — {month or 'current'}\n"]

        for c in items:
            amount = float(c.get("amount", 0))
            ratio = pct(amount, total) if total > 0 else "0%"
            icon = c.get("icon", "")
            lines.append(f"  {icon} {c['name']}: {fmt_amount(amount)} ({ratio})")

            children = c.get("children", [])
            for child in children:
                child_amount = float(child.get("amount", 0))
                lines.append(f"    └ {child['name']}: {fmt_amount(child_amount)}")

        lines.append(f"\nTotal: {fmt_amount(total)}")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_subscription_forecast(months: int = 3) -> str:
    """訂閱未來 N 月預估支出"""
    try:
        result = await to_thread(client.subscription_forecast, months=months)
        items = result if isinstance(result, list) else result.get("months", [])

        if not items:
            return "No active subscriptions for forecast."

        lines = [f"# Subscription Forecast (next {months} months)\n"]
        grand_total = 0
        for m in items:
            month_total = float(m.get("total", 0))
            grand_total += month_total
            lines.append(f"## {m['month']}: {fmt_amount(month_total)}")
            for s in m.get("subscriptions", []):
                lines.append(f"  - {s['name']}: {fmt_amount(s['amount'])}")

        lines.append(f"\nTotal forecast: {fmt_amount(grand_total)}")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_installment_forecast(months: int = 6) -> str:
    """分期未來支出預估（各月份分期扣款明細）"""
    try:
        result = await to_thread(client.installment_forecast, months=months)
        items = result if isinstance(result, list) else result.get("months", [])

        if not items:
            return "No active installments for forecast."

        lines = [f"# Installment Forecast (next {months} months)\n"]
        grand_total = 0
        for m in items:
            month_total = float(m.get("total", 0))
            grand_total += month_total
            lines.append(f"## {m['month']}: {fmt_amount(month_total)}")
            for p in m.get("installments", []):
                n = p.get("installment_number", "?")
                total_n = p.get("num_installments", "?")
                lines.append(f"  - {p['description']}: {fmt_amount(p['amount'])} (#{n}/{total_n})")

        lines.append(f"\nTotal forecast: {fmt_amount(grand_total)}")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_export(
    data_type: str,
    format: str = "csv",
    month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_archived: bool = False,
) -> str:
    """匯出財務資料（CSV / JSON，含隱密過濾）"""
    try:
        resp = await to_thread(
            client.export_data,
            data_type=data_type,
            format=format,
            month=month,
            start_date=start_date,
            end_date=end_date,
            include_archived=include_archived,
        )

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            data = resp.json()
            if isinstance(data, dict) and "download_url" in data:
                return f"Export ready.\nDownload: {data['download_url']}"
            return (
                f"Export ({data_type}, {format}):\n\n"
                f"{json.dumps(data, indent=2, ensure_ascii=False)}"
            )

        # CSV / plain text
        text = resp.text
        line_count = text.count("\n")
        if line_count > 50:
            preview = "\n".join(text.split("\n")[:20])
            return (
                f"Export ({data_type}, {format}): {line_count} rows\n\n"
                f"Preview (first 20 rows):\n{preview}\n\n... ({line_count - 20} more rows)"
            )
        return f"Export ({data_type}, {format}):\n\n{text}"
    except (APIError, APIConnectionError) as e:
        return f"Finance error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()
