#!/usr/bin/env python3
"""Finance MCP Server — core CRUD thin adapter over Core API.

10 tools: transactions CRUD, subscriptions CRUD, categories, suggest, privacy toggle.
Uses workshop.clients.finance SDK instead of raw httpx calls.

Usage:
    python3 mcp/finance/server.py

Configure in ~/.claude.json:
    "workshop-finance": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/finance/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:10000",
            "FINANCE_SPACE_ID": "default"
        }
    }
"""

from asyncio import to_thread
from typing import Literal

from mcp.server.fastmcp import FastMCP
from workshop.clients.finance import FinanceClient
from workshop.mcp_helpers import build_body, fmt_amount, mcp_error_handler

mcp = FastMCP("workshop-finance")
client = FinanceClient()


# ======================== Tools ========================


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_add_transaction(
    type: Literal["income", "expense", "transfer"],
    amount: float,
    wallet_id: str,
    description: str = "",
    merchant: str = "",
    payment_method: str = "",
    payment_detail: str = "",
    category_id: str = "",
    transfer_to_wallet_id: str = "",
    tags: list[str] | None = None,
    transacted_at: str = "",
    is_private: bool = False,
    invoice_number: str = "",
    fee: float = 0,
) -> str:
    """Create a financial transaction (income/expense/transfer) with amount, wallet, merchant, category, tags. 新增交易。"""
    body = build_body(
        {"type": type, "amount": amount, "wallet_id": wallet_id},
        description=description,
        merchant=merchant,
        payment_method=payment_method,
        payment_detail=payment_detail,
        category_id=category_id,
        transfer_to_wallet_id=transfer_to_wallet_id,
        tags=tags,
        transacted_at=transacted_at,
        is_private=is_private or None,
        invoice_number=invoice_number,
        fee=fee or None,
    )
    result = await to_thread(client.create_transaction, body)
    return (
        f"Transaction created.\n"
        f"ID: {result['id']}\n"
        f"Type: {result['type']} | Amount: {fmt_amount(result['amount'])}\n"
        f"Merchant: {result.get('merchant', '-')} | Wallet: {result.get('wallet_id', '-')}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_update_transaction(
    id: str,
    amount: float | None = None,
    description: str = "",
    merchant: str = "",
    payment_method: str = "",
    payment_detail: str = "",
    category_id: str = "",
    wallet_id: str = "",
    tags: list[str] | None = None,
    transacted_at: str = "",
    invoice_number: str = "",
    fee: float | None = None,
) -> str:
    """Update transaction fields: amount, merchant, category, wallet, tags, payment method. 更新交易。"""
    if not id:
        return "Error: transaction id is required"
    body = build_body(
        {},
        amount=amount,
        description=description,
        merchant=merchant,
        payment_method=payment_method,
        payment_detail=payment_detail,
        category_id=category_id,
        wallet_id=wallet_id,
        tags=tags,
        transacted_at=transacted_at,
        invoice_number=invoice_number,
        fee=fee,
    )
    result = await to_thread(client.update_transaction, id, body)
    return (
        f"Transaction {id} updated.\n"
        f"Amount: {fmt_amount(result.get('amount', 0))} | Type: {result.get('type', '-')}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_delete_transaction(id: str) -> str:
    """Soft-delete a financial transaction by ID. 刪除交易。"""
    await to_thread(client.delete_transaction, id)
    return f"Transaction {id} deleted."


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_list_transactions(
    month: str = "",
    type: str = "",
    category_id: str = "",
    wallet_id: str = "",
    payment_method: str = "",
    tag: str = "",
    search: str = "",
    installment_plan_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List transactions with filters: month, type, category, wallet, payment method, tag, keyword. 交易列表。"""
    result = await to_thread(
        client.list_transactions,
        year_month=month or None,
        type=type or None,
        category_id=category_id or None,
        wallet_id=wallet_id or None,
        tag=tag or None,
        search=search or None,
        page=page,
        page_size=page_size,
    )
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return "No transactions found."

    lines = [f"# Transactions ({total} total)\n"]
    for t in items:
        icon = {"income": "+", "expense": "-", "transfer": "~"}
        prefix = icon.get(t["type"], "?")
        desc = t.get("description") or t.get("merchant") or "-"
        date = t.get("transacted_at", "")[:10]
        lines.append(
            f"  {prefix} {fmt_amount(t['amount'])}  {desc}  [{date}]  "
            f"({t.get('payment_method', '-')}) id={t['id'][:8]}"
        )

    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_add_subscription(
    name: str,
    amount: float,
    billing_cycle: Literal["monthly", "yearly", "weekly"],
    start_date: str,
    billing_day: int | None = None,
    category_id: str = "",
    wallet_id: str = "",
    payment_method: str = "",
    payment_detail: str = "",
    end_date: str = "",
    notes: str = "",
    is_private: bool = False,
) -> str:
    """Create a recurring subscription (monthly/yearly/weekly) with amount, wallet, billing cycle. 新增訂閱。"""
    body = build_body(
        {"name": name, "amount": amount, "billing_cycle": billing_cycle, "start_date": start_date},
        billing_day=billing_day,
        category_id=category_id,
        wallet_id=wallet_id,
        payment_method=payment_method,
        payment_detail=payment_detail,
        end_date=end_date,
        notes=notes,
        is_private=is_private or None,
    )
    result = await to_thread(client.create_subscription, body)
    return (
        f"Subscription created.\n"
        f"ID: {result['id']}\n"
        f"Name: {result['name']} | {fmt_amount(result['amount'])} / {result['billing_cycle']}\n"
        f"Next billing: {result.get('next_billing', '-')}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_update_subscription(
    id: str,
    name: str = "",
    amount: float | None = None,
    billing_cycle: str = "",
    billing_day: int | None = None,
    category_id: str = "",
    wallet_id: str = "",
    payment_method: str = "",
    payment_detail: str = "",
    end_date: str = "",
    status: str = "",
    notes: str = "",
) -> str:
    """Update subscription: name, amount, cycle, wallet, or change status to paused/cancelled. 更新訂閱。"""
    if not id:
        return "Error: subscription id is required"
    body = build_body(
        {},
        name=name,
        amount=amount,
        billing_cycle=billing_cycle,
        billing_day=billing_day,
        category_id=category_id,
        wallet_id=wallet_id,
        payment_method=payment_method,
        payment_detail=payment_detail,
        end_date=end_date,
        status=status,
        notes=notes,
    )
    result = await to_thread(client.update_subscription, id, body)
    return (
        f"Subscription {id} updated.\n"
        f"Name: {result.get('name', '-')} | Status: {result.get('status', '-')}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_list_subscriptions(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List subscriptions with status filter (active/paused/cancelled), amounts, next billing dates. 訂閱列表。"""
    result = await to_thread(
        client.list_subscriptions,
        status=status or None,
        page=page,
        page_size=page_size,
    )
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return "No subscriptions found."

    lines = [f"# Subscriptions ({total} total)\n"]
    for s in items:
        status_icon = {"active": "*", "paused": "||", "cancelled": "x"}.get(
            s.get("status", ""), "?"
        )
        lines.append(
            f"  {status_icon} {s['name']}  {fmt_amount(s['amount'])} / {s['billing_cycle']}  "
            f"next: {s.get('next_billing', '-')}  id={s['id'][:8]}"
        )

    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_manage_categories(
    action: Literal["list", "create", "update", "deactivate"],
    id: str = "",
    name: str = "",
    parent_id: str = "",
    icon: str = "",
    color: str = "",
    sort_order: int | None = None,
    is_private: bool = False,
) -> str:
    """Manage expense categories: list tree, create, update (rename/reparent), deactivate. 分類管理。"""
    if action == "list":
        result = await to_thread(client.list_categories)
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return "No categories found."
        lines = ["# Categories\n"]
        for c in items:
            indent = "  " if c.get("parent_id") else ""
            cat_icon = c.get("icon", "")
            private = " [private]" if c.get("is_private") else ""
            lines.append(f"{indent}{cat_icon} {c['name']}{private}  id={c['id'][:8]}")
        return "\n".join(lines)

    if action == "create":
        if not name:
            return "Error: name is required for create"
        body = build_body(
            {"name": name},
            parent_id=parent_id,
            icon=icon,
            color=color,
            sort_order=sort_order,
            is_private=is_private or None,
        )
        result = await to_thread(client.create_category, body)
        return (
            f"Category created: {result.get('icon', '')} {result['name']} (id={result['id'][:8]})"
        )

    if action == "update":
        if not id:
            return "Error: id is required for update"
        body = build_body(
            {},
            name=name,
            parent_id=parent_id,
            icon=icon,
            color=color,
            sort_order=sort_order,
            is_private=is_private or None,
        )
        result = await to_thread(client.update_category, id, body)
        return f"Category {id[:8]} updated: {result['name']}"

    if action == "deactivate":
        if not id:
            return "Error: id is required for deactivate"
        await to_thread(client.update_category, id, {"is_active": False})
        return f"Category {id[:8]} deactivated."

    return f"Unknown action: {action}"


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_suggest(
    field: Literal["merchant", "tag", "category", "payment_detail"],
    prefix: str = "",
) -> str:
    """欄位自動補全（商家、標籤、分類、付款方式）"""
    # suggest endpoint not in SDK (not a standard CRUD route), use _get directly
    params: dict[str, str] = {"field": field}
    if prefix:
        params["prefix"] = prefix
    result = await to_thread(client._get, "/suggest", params)
    suggestions = result if isinstance(result, list) else result.get("items", [])

    if not suggestions:
        return f"No suggestions for {field}."

    return f"Suggestions for {field}:\n" + "\n".join(f"  - {s}" for s in suggestions)


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_toggle_privacy(
    entity_type: Literal["transaction", "subscription", "category", "wallet", "installment_plan"],
    entity_id: str,
    is_private: bool,
) -> str:
    """Toggle privacy flag on a finance entity (transaction, subscription, category, wallet, installment). 隱密切換。"""
    update_map = {
        "transaction": lambda: client.update_transaction(entity_id, {"is_private": is_private}),
        "subscription": lambda: client.update_subscription(entity_id, {"is_private": is_private}),
        "category": lambda: client.update_category(entity_id, {"is_private": is_private}),
        "wallet": lambda: client.update_wallet(entity_id, {"is_private": is_private}),
        "installment_plan": lambda: client.update_installment(
            entity_id, {"is_private": is_private}
        ),
    }
    fn = update_map.get(entity_type)
    if not fn:
        return f"Unknown entity type: {entity_type}"

    await to_thread(fn)
    state = "private" if is_private else "public"
    return f"{entity_type} {entity_id[:8]} set to {state}."


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()
