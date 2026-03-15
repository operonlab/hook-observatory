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
            "CORE_API_URL": "http://localhost:8801",
            "FINANCE_SPACE_ID": "default"
        }
    }
"""

import asyncio
from asyncio import to_thread
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.finance import FinanceClient

server = Server("workshop-finance")
client = FinanceClient()


# ======================== Helpers ========================


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def fmt_amount(amount: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(amount):,.0f}"


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="finance_add_transaction",
            description="新增交易（收入/支出/轉帳）",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["income", "expense", "transfer"],
                        "description": "交易類型",
                    },
                    "amount": {"type": "number", "description": "金額"},
                    "description": {"type": "string", "description": "交易描述"},
                    "merchant": {"type": "string", "description": "商家名稱"},
                    "payment_method": {
                        "type": "string",
                        "enum": ["cash", "credit_card", "debit_card", "e_payment", "bank_transfer"],
                        "description": "付款方式",
                    },
                    "payment_detail": {"type": "string", "description": "具體卡片/帳戶名稱"},
                    "category_id": {"type": "string", "description": "分類 ID"},
                    "wallet_id": {"type": "string", "description": "錢包 ID（必填）"},
                    "transfer_to_wallet_id": {"type": "string", "description": "轉帳目標錢包 ID"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "自訂標籤",
                    },
                    "transacted_at": {
                        "type": "string",
                        "description": "交易時間（ISO 8601），預設為現在",
                    },
                    "is_private": {"type": "boolean", "default": False},
                    "invoice_number": {"type": "string", "description": "發票號碼"},
                    "fee": {"type": "number", "description": "手續費", "default": 0},
                },
                "required": ["type", "amount", "wallet_id"],
            },
        ),
        Tool(
            name="finance_update_transaction",
            description="更新交易欄位",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "交易 ID"},
                    "amount": {"type": "number"},
                    "description": {"type": "string"},
                    "merchant": {"type": "string"},
                    "payment_method": {"type": "string"},
                    "payment_detail": {"type": "string"},
                    "category_id": {"type": "string"},
                    "wallet_id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "transacted_at": {"type": "string"},
                    "invoice_number": {"type": "string"},
                    "fee": {"type": "number"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="finance_delete_transaction",
            description="刪除交易",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "交易 ID"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="finance_list_transactions",
            description="列出交易（支援多種過濾條件）",
            inputSchema={
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "月份過濾 (YYYY-MM)"},
                    "type": {"type": "string", "enum": ["income", "expense", "transfer"]},
                    "category_id": {"type": "string", "description": "分類 ID"},
                    "wallet_id": {"type": "string", "description": "錢包 ID"},
                    "payment_method": {"type": "string"},
                    "tag": {"type": "string", "description": "標籤過濾"},
                    "search": {"type": "string", "description": "全文搜尋（商家/描述）"},
                    "installment_plan_id": {"type": "string", "description": "分期計畫 ID"},
                    "status": {
                        "type": "string",
                        "enum": ["completed", "scheduled", "cancelled", "pending"],
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="finance_add_subscription",
            description="新增週期性訂閱",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "訂閱名稱 (e.g. Netflix)"},
                    "amount": {"type": "number", "description": "金額"},
                    "billing_cycle": {
                        "type": "string",
                        "enum": ["monthly", "yearly", "weekly"],
                    },
                    "billing_day": {"type": "integer", "description": "扣款日 (1-31)"},
                    "category_id": {"type": "string"},
                    "wallet_id": {"type": "string", "description": "關聯錢包 ID"},
                    "payment_method": {"type": "string"},
                    "payment_detail": {"type": "string"},
                    "start_date": {"type": "string", "description": "開始日期 (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "結束日期"},
                    "notes": {"type": "string"},
                    "is_private": {"type": "boolean", "default": False},
                },
                "required": ["name", "amount", "billing_cycle", "start_date"],
            },
        ),
        Tool(
            name="finance_update_subscription",
            description="更新訂閱（含暫停/取消）",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "訂閱 ID"},
                    "name": {"type": "string"},
                    "amount": {"type": "number"},
                    "billing_cycle": {"type": "string"},
                    "billing_day": {"type": "integer"},
                    "category_id": {"type": "string"},
                    "wallet_id": {"type": "string"},
                    "payment_method": {"type": "string"},
                    "payment_detail": {"type": "string"},
                    "end_date": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "cancelled"],
                        "description": "狀態變更",
                    },
                    "notes": {"type": "string"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="finance_list_subscriptions",
            description="列出訂閱",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "cancelled"],
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="finance_manage_categories",
            description="分類管理（新增/編輯/移動/停用）",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "update", "deactivate"],
                    },
                    "id": {"type": "string", "description": "分類 ID（update/deactivate 時必填）"},
                    "name": {"type": "string", "description": "分類名稱"},
                    "parent_id": {"type": "string", "description": "父分類 ID（NULL = 頂層）"},
                    "icon": {"type": "string", "description": "圖示 emoji"},
                    "color": {"type": "string", "description": "顏色 hex"},
                    "sort_order": {"type": "integer"},
                    "is_private": {"type": "boolean", "default": False},
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="finance_suggest",
            description="欄位自動補全（商家、標籤、分類、付款方式）",
            inputSchema={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": ["merchant", "tag", "category", "payment_detail"],
                        "description": "要補全的欄位",
                    },
                    "prefix": {"type": "string", "description": "輸入前綴"},
                },
                "required": ["field"],
            },
        ),
        Tool(
            name="finance_toggle_privacy",
            description="切換項目隱密狀態",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": [
                            "transaction",
                            "subscription",
                            "category",
                            "wallet",
                            "installment_plan",
                        ],
                        "description": "實體類型",
                    },
                    "entity_id": {"type": "string", "description": "實體 ID"},
                    "is_private": {"type": "boolean", "description": "設定隱密狀態"},
                },
                "required": ["entity_type", "entity_id", "is_private"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        match name:
            case "finance_add_transaction":
                return await handle_add_transaction(arguments)
            case "finance_update_transaction":
                return await handle_update_transaction(arguments)
            case "finance_delete_transaction":
                return await handle_delete_transaction(arguments)
            case "finance_list_transactions":
                return await handle_list_transactions(arguments)
            case "finance_add_subscription":
                return await handle_add_subscription(arguments)
            case "finance_update_subscription":
                return await handle_update_subscription(arguments)
            case "finance_list_subscriptions":
                return await handle_list_subscriptions(arguments)
            case "finance_manage_categories":
                return await handle_manage_categories(arguments)
            case "finance_suggest":
                return await handle_suggest(arguments)
            case "finance_toggle_privacy":
                return await handle_toggle_privacy(arguments)
            case _:
                return text_result(f"Unknown tool: {name}")
    except APIError as e:
        return text_result(f"API error {e.status_code}: {e.detail}")
    except APIConnectionError as e:
        return text_result(str(e))
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Tool Implementations ========================


async def handle_add_transaction(args: dict) -> list[TextContent]:
    body: dict[str, Any] = {
        "type": args["type"],
        "amount": args["amount"],
        "wallet_id": args["wallet_id"],
    }
    for field in (
        "description",
        "merchant",
        "payment_method",
        "payment_detail",
        "category_id",
        "transfer_to_wallet_id",
        "tags",
        "transacted_at",
        "is_private",
        "invoice_number",
        "fee",
    ):
        if field in args:
            body[field] = args[field]

    result = await to_thread(client.create_transaction, body)
    return text_result(
        f"Transaction created.\n"
        f"ID: {result['id']}\n"
        f"Type: {result['type']} | Amount: {fmt_amount(result['amount'])}\n"
        f"Merchant: {result.get('merchant', '-')} | Wallet: {result.get('wallet_id', '-')}"
    )


async def handle_update_transaction(args: dict) -> list[TextContent]:
    txn_id = args.pop("id", None)
    if not txn_id:
        return text_result("Error: transaction id is required")
    result = await to_thread(client.update_transaction, txn_id, args)
    return text_result(
        f"Transaction {txn_id} updated.\n"
        f"Amount: {fmt_amount(result.get('amount', 0))} | Type: {result.get('type', '-')}"
    )


async def handle_delete_transaction(args: dict) -> list[TextContent]:
    txn_id = args["id"]
    await to_thread(client.delete_transaction, txn_id)
    return text_result(f"Transaction {txn_id} deleted.")


async def handle_list_transactions(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_transactions,
        year_month=args.get("month"),
        type=args.get("type"),
        category_id=args.get("category_id"),
        wallet_id=args.get("wallet_id"),
        tag=args.get("tag"),
        search=args.get("search"),
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return text_result("No transactions found.")

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

    return text_result("\n".join(lines))


async def handle_add_subscription(args: dict) -> list[TextContent]:
    body: dict[str, Any] = {
        "name": args["name"],
        "amount": args["amount"],
        "billing_cycle": args["billing_cycle"],
        "start_date": args["start_date"],
    }
    for field in (
        "billing_day",
        "category_id",
        "wallet_id",
        "payment_method",
        "payment_detail",
        "end_date",
        "notes",
        "is_private",
    ):
        if field in args:
            body[field] = args[field]

    result = await to_thread(client.create_subscription, body)
    return text_result(
        f"Subscription created.\n"
        f"ID: {result['id']}\n"
        f"Name: {result['name']} | {fmt_amount(result['amount'])} / {result['billing_cycle']}\n"
        f"Next billing: {result.get('next_billing', '-')}"
    )


async def handle_update_subscription(args: dict) -> list[TextContent]:
    sub_id = args.pop("id", None)
    if not sub_id:
        return text_result("Error: subscription id is required")
    result = await to_thread(client.update_subscription, sub_id, args)
    return text_result(
        f"Subscription {sub_id} updated.\n"
        f"Name: {result.get('name', '-')} | Status: {result.get('status', '-')}"
    )


async def handle_list_subscriptions(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_subscriptions,
        status=args.get("status"),
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return text_result("No subscriptions found.")

    lines = [f"# Subscriptions ({total} total)\n"]
    for s in items:
        status_icon = {"active": "*", "paused": "||", "cancelled": "x"}.get(
            s.get("status", ""), "?"
        )
        lines.append(
            f"  {status_icon} {s['name']}  {fmt_amount(s['amount'])} / {s['billing_cycle']}  "
            f"next: {s.get('next_billing', '-')}  id={s['id'][:8]}"
        )

    return text_result("\n".join(lines))


async def handle_manage_categories(args: dict) -> list[TextContent]:
    action = args["action"]

    if action == "list":
        result = await to_thread(client.list_categories)
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return text_result("No categories found.")
        lines = ["# Categories\n"]
        for c in items:
            indent = "  " if c.get("parent_id") else ""
            icon = c.get("icon", "")
            private = " [private]" if c.get("is_private") else ""
            lines.append(f"{indent}{icon} {c['name']}{private}  id={c['id'][:8]}")
        return text_result("\n".join(lines))

    if action == "create":
        body: dict[str, Any] = {"name": args["name"]}
        for field in ("parent_id", "icon", "color", "sort_order", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await to_thread(client.create_category, body)
        return text_result(
            f"Category created: {result.get('icon', '')} {result['name']} (id={result['id'][:8]})"
        )

    if action == "update":
        cat_id = args["id"]
        body = {}
        for field in ("name", "parent_id", "icon", "color", "sort_order", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await to_thread(client.update_category, cat_id, body)
        return text_result(f"Category {cat_id[:8]} updated: {result['name']}")

    if action == "deactivate":
        cat_id = args["id"]
        result = await to_thread(client.update_category, cat_id, {"is_active": False})
        return text_result(f"Category {cat_id[:8]} deactivated.")

    return text_result(f"Unknown action: {action}")


async def handle_suggest(args: dict) -> list[TextContent]:
    # suggest endpoint not in SDK (not a standard CRUD route), use _get directly
    params = {"field": args["field"]}
    if "prefix" in args:
        params["prefix"] = args["prefix"]
    result = await to_thread(client._get, "/suggest", params)
    suggestions = result if isinstance(result, list) else result.get("items", [])

    if not suggestions:
        return text_result(f"No suggestions for {args['field']}.")

    return text_result(
        f"Suggestions for {args['field']}:\n" + "\n".join(f"  - {s}" for s in suggestions)
    )


async def handle_toggle_privacy(args: dict) -> list[TextContent]:
    entity_type = args["entity_type"]
    entity_id = args["entity_id"]
    is_private = args["is_private"]

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
        return text_result(f"Unknown entity type: {entity_type}")

    await to_thread(fn)
    state = "private" if is_private else "public"
    return text_result(f"{entity_type} {entity_id[:8]} set to {state}.")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
