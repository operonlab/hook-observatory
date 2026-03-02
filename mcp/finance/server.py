#!/usr/bin/env python3
"""Finance MCP Server — core CRUD thin adapter over Core API.

10 tools: transactions CRUD, subscriptions CRUD, categories, suggest, privacy toggle.

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

import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("FINANCE_SPACE_ID", "default")
BASE = f"{CORE_API}/api/finance"

server = Server("workshop-finance")


# ======================== Helpers ========================


async def api_get(path: str, params: dict | None = None) -> dict:
    p = {"space_id": SPACE_ID}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE}{path}", params=p)
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        payload = {"space_id": SPACE_ID, **(body or {})}
        resp = await client.post(f"{BASE}{path}", json=payload)
        resp.raise_for_status()
        return resp.json()


async def api_put(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(f"{BASE}{path}", json=body)
        resp.raise_for_status()
        return resp.json()


async def api_delete(path: str) -> bool:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(f"{BASE}{path}")
        return resp.status_code in (200, 204)


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
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "自訂標籤"},
                    "transacted_at": {"type": "string", "description": "交易時間（ISO 8601），預設為現在"},
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
                    "status": {"type": "string", "enum": ["completed", "scheduled", "cancelled", "pending"]},
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
                        "enum": ["transaction", "subscription", "category", "wallet", "installment_plan", "budget"],
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
    except httpx.HTTPStatusError as e:
        return text_result(f"API error {e.response.status_code}: {e.response.text}")
    except httpx.ConnectError:
        return text_result(
            f"Cannot connect to Core API at {CORE_API}. "
            "Start the server: cd core && uvicorn src.main:app --port 8801"
        )


# ======================== Tool Implementations ========================


async def handle_add_transaction(args: dict) -> list[TextContent]:
    body = {
        "type": args["type"],
        "amount": args["amount"],
        "wallet_id": args["wallet_id"],
    }
    for field in (
        "description", "merchant", "payment_method", "payment_detail",
        "category_id", "transfer_to_wallet_id", "tags", "transacted_at",
        "is_private", "invoice_number", "fee",
    ):
        if field in args:
            body[field] = args[field]

    result = await api_post("/transactions", body)
    return text_result(
        f"Transaction created.\n"
        f"ID: {result['id']}\n"
        f"Type: {result['type']} | Amount: {fmt_amount(result['amount'])}\n"
        f"Merchant: {result.get('merchant', '-')} | Wallet: {result.get('wallet_id', '-')}"
    )


async def handle_update_transaction(args: dict) -> list[TextContent]:
    txn_id = args.pop("id")
    result = await api_put(f"/transactions/{txn_id}", args)
    return text_result(
        f"Transaction {txn_id} updated.\n"
        f"Amount: {fmt_amount(result['amount'])} | Type: {result['type']}"
    )


async def handle_delete_transaction(args: dict) -> list[TextContent]:
    txn_id = args["id"]
    ok = await api_delete(f"/transactions/{txn_id}")
    if ok:
        return text_result(f"Transaction {txn_id} deleted.")
    return text_result(f"Failed to delete transaction {txn_id}.")


async def handle_list_transactions(args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    for key in (
        "month", "type", "category_id", "wallet_id", "payment_method",
        "tag", "search", "installment_plan_id", "status",
    ):
        if key in args:
            params[key] = str(args[key])
    params["page"] = str(args.get("page", 1))
    params["page_size"] = str(args.get("page_size", 20))

    result = await api_get("/transactions", params)
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return text_result("No transactions found.")

    lines = [f"# Transactions ({total} total)\n"]
    for t in items:
        icon = {"income": "+", "expense": "-", "transfer": "↔"}
        prefix = icon.get(t["type"], "?")
        desc = t.get("description") or t.get("merchant") or "-"
        date = t.get("transacted_at", "")[:10]
        lines.append(
            f"  {prefix} {fmt_amount(t['amount'])}  {desc}  [{date}]  "
            f"({t.get('payment_method', '-')}) id={t['id'][:8]}"
        )

    return text_result("\n".join(lines))


async def handle_add_subscription(args: dict) -> list[TextContent]:
    body = {
        "name": args["name"],
        "amount": args["amount"],
        "billing_cycle": args["billing_cycle"],
        "start_date": args["start_date"],
    }
    for field in (
        "billing_day", "category_id", "wallet_id", "payment_method",
        "payment_detail", "end_date", "notes", "is_private",
    ):
        if field in args:
            body[field] = args[field]

    result = await api_post("/subscriptions", body)
    return text_result(
        f"Subscription created.\n"
        f"ID: {result['id']}\n"
        f"Name: {result['name']} | {fmt_amount(result['amount'])} / {result['billing_cycle']}\n"
        f"Next billing: {result.get('next_billing', '-')}"
    )


async def handle_update_subscription(args: dict) -> list[TextContent]:
    sub_id = args.pop("id")
    result = await api_put(f"/subscriptions/{sub_id}", args)
    return text_result(
        f"Subscription {sub_id} updated.\n"
        f"Name: {result['name']} | Status: {result.get('status', '-')}"
    )


async def handle_list_subscriptions(args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    if "status" in args:
        params["status"] = args["status"]
    params["page"] = str(args.get("page", 1))
    params["page_size"] = str(args.get("page_size", 20))

    result = await api_get("/subscriptions", params)
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return text_result("No subscriptions found.")

    lines = [f"# Subscriptions ({total} total)\n"]
    for s in items:
        status_icon = {"active": "●", "paused": "⏸", "cancelled": "✕"}.get(s.get("status", ""), "?")
        lines.append(
            f"  {status_icon} {s['name']}  {fmt_amount(s['amount'])} / {s['billing_cycle']}  "
            f"next: {s.get('next_billing', '-')}  id={s['id'][:8]}"
        )

    return text_result("\n".join(lines))


async def handle_manage_categories(args: dict) -> list[TextContent]:
    action = args["action"]

    if action == "list":
        result = await api_get("/categories")
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return text_result("No categories found.")
        lines = ["# Categories\n"]
        for c in items:
            indent = "  " if c.get("parent_id") else ""
            icon = c.get("icon", "")
            private = " 🔒" if c.get("is_private") else ""
            lines.append(f"{indent}{icon} {c['name']}{private}  id={c['id'][:8]}")
        return text_result("\n".join(lines))

    if action == "create":
        body: dict[str, Any] = {"name": args["name"]}
        for field in ("parent_id", "icon", "color", "sort_order", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await api_post("/categories", body)
        return text_result(f"Category created: {result.get('icon', '')} {result['name']} (id={result['id'][:8]})")

    if action == "update":
        cat_id = args["id"]
        body = {}
        for field in ("name", "parent_id", "icon", "color", "sort_order", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await api_put(f"/categories/{cat_id}", body)
        return text_result(f"Category {cat_id[:8]} updated: {result['name']}")

    if action == "deactivate":
        cat_id = args["id"]
        result = await api_put(f"/categories/{cat_id}", {"is_active": False})
        return text_result(f"Category {cat_id[:8]} deactivated.")

    return text_result(f"Unknown action: {action}")


async def handle_suggest(args: dict) -> list[TextContent]:
    params: dict[str, str] = {"field": args["field"]}
    if "prefix" in args:
        params["prefix"] = args["prefix"]

    result = await api_get("/suggest", params)
    suggestions = result if isinstance(result, list) else result.get("items", [])

    if not suggestions:
        return text_result(f"No suggestions for {args['field']}.")

    return text_result(
        f"Suggestions for {args['field']}:\n"
        + "\n".join(f"  - {s}" for s in suggestions)
    )


async def handle_toggle_privacy(args: dict) -> list[TextContent]:
    entity_type = args["entity_type"]
    entity_id = args["entity_id"]
    is_private = args["is_private"]

    # Map entity type to API path
    path_map = {
        "transaction": f"/transactions/{entity_id}",
        "subscription": f"/subscriptions/{entity_id}",
        "category": f"/categories/{entity_id}",
        "wallet": f"/wallets/{entity_id}",
        "installment_plan": f"/installments/{entity_id}",
        "budget": f"/budgets/{entity_id}",
    }
    path = path_map.get(entity_type)
    if not path:
        return text_result(f"Unknown entity type: {entity_type}")

    await api_put(path, {"is_private": is_private})
    state = "private 🔒" if is_private else "public"
    return text_result(f"{entity_type} {entity_id[:8]} set to {state}.")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
