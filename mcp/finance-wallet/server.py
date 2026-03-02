#!/usr/bin/env python3
"""Finance Wallet MCP Server — wallet + installment thin adapter over Core API.

8 tools: wallet CRUD, sync, reconcile, transfer, installment CRUD, payoff, attachment.

Usage:
    python3 mcp/finance-wallet/server.py

Configure in ~/.claude.json:
    "workshop-finance-wallet": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/finance-wallet/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:8801",
            "FINANCE_SPACE_ID": "default"
        }
    }
"""

import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("FINANCE_SPACE_ID", "default")
BASE = f"{CORE_API}/api/finance"

server = Server("workshop-finance-wallet")


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


async def api_post_file(path: str, file_path: str, filename: str, content_type: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, content_type)}
            resp = await client.post(
                f"{BASE}{path}",
                files=files,
                params={"space_id": SPACE_ID},
            )
            resp.raise_for_status()
            return resp.json()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def fmt_amount(amount: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(amount):,.0f}"


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="finance_manage_wallets",
            description="錢包管理（列表/新增/編輯/停用）",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "update", "deactivate"],
                    },
                    "id": {"type": "string", "description": "錢包 ID（update/deactivate 時必填）"},
                    "name": {"type": "string", "description": "錢包名稱"},
                    "type": {
                        "type": "string",
                        "enum": ["bank_account", "credit_card", "cash", "e_wallet", "investment"],
                        "description": "錢包類型",
                    },
                    "currency": {"type": "string", "default": "TWD"},
                    "initial_balance": {"type": "number", "description": "初始餘額"},
                    "credit_limit": {"type": "number", "description": "信用卡額度"},
                    "icon": {"type": "string"},
                    "color": {"type": "string"},
                    "sort_order": {"type": "integer"},
                    "is_private": {"type": "boolean", "default": False},
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="finance_sync_wallet",
            description="同步錢包餘額，產生 snapshot（對帳用）",
            inputSchema={
                "type": "object",
                "properties": {
                    "wallet_id": {"type": "string", "description": "錢包 ID"},
                    "actual_balance": {"type": "number", "description": "使用者回報的實際餘額"},
                    "snapshot_type": {
                        "type": "string",
                        "enum": ["reconciliation", "valuation"],
                        "default": "reconciliation",
                        "description": "reconciliation=對帳, valuation=市值評估（投資用）",
                    },
                    "notes": {"type": "string", "description": "備註"},
                },
                "required": ["wallet_id", "actual_balance"],
            },
        ),
        Tool(
            name="finance_reconcile",
            description="錢包對帳摘要（各錢包系統餘額 vs 差額趨勢）",
            inputSchema={
                "type": "object",
                "properties": {
                    "wallet_id": {"type": "string", "description": "指定錢包（空=全部）"},
                },
            },
        ),
        Tool(
            name="finance_transfer",
            description="錢包間轉帳",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_wallet_id": {"type": "string", "description": "來源錢包 ID"},
                    "to_wallet_id": {"type": "string", "description": "目標錢包 ID"},
                    "amount": {"type": "number", "description": "轉帳金額"},
                    "description": {"type": "string", "description": "轉帳描述"},
                    "fee": {"type": "number", "description": "手續費", "default": 0},
                    "transacted_at": {"type": "string", "description": "轉帳時間（ISO 8601）"},
                },
                "required": ["from_wallet_id", "to_wallet_id", "amount"],
            },
        ),
        Tool(
            name="finance_add_installment",
            description="新增分期付款計畫（自動產生 scheduled transactions）",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "分期描述 (e.g. MacBook Pro)"},
                    "total_amount": {"type": "number", "description": "總金額"},
                    "num_installments": {"type": "integer", "description": "分期數 (3/6/12/24)"},
                    "wallet_id": {"type": "string", "description": "扣款錢包 ID"},
                    "payment_method": {"type": "string", "description": "付款方式"},
                    "payment_detail": {"type": "string"},
                    "merchant": {"type": "string"},
                    "category_id": {"type": "string"},
                    "start_date": {"type": "string", "description": "首期日期 (YYYY-MM-DD)"},
                    "billing_day": {"type": "integer", "description": "每月扣款日 (1-31)"},
                    "interest_rate": {"type": "number", "description": "年利率（0=零利率）", "default": 0},
                    "fee_type": {
                        "type": "string",
                        "enum": ["none", "interest", "fee_per_period", "total_fee"],
                        "default": "none",
                    },
                    "fee_per_installment": {"type": "number", "description": "每期手續費", "default": 0},
                    "is_private": {"type": "boolean", "default": False},
                },
                "required": ["description", "total_amount", "num_installments", "wallet_id", "payment_method", "start_date"],
            },
        ),
        Tool(
            name="finance_list_installments",
            description="列出分期付款計畫",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "completed", "cancelled"],
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="finance_installment_payoff",
            description="分期提前還款（將所有剩餘期數標記為 completed）",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "分期計畫 ID"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="finance_upload_attachment",
            description="上傳交易附件照片",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "交易 ID"},
                    "file_path": {"type": "string", "description": "本地檔案路徑"},
                    "filename": {"type": "string", "description": "檔案名稱"},
                    "content_type": {
                        "type": "string",
                        "description": "MIME type (e.g. image/jpeg)",
                        "default": "image/jpeg",
                    },
                },
                "required": ["transaction_id", "file_path"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        match name:
            case "finance_manage_wallets":
                return await handle_manage_wallets(arguments)
            case "finance_sync_wallet":
                return await handle_sync_wallet(arguments)
            case "finance_reconcile":
                return await handle_reconcile(arguments)
            case "finance_transfer":
                return await handle_transfer(arguments)
            case "finance_add_installment":
                return await handle_add_installment(arguments)
            case "finance_list_installments":
                return await handle_list_installments(arguments)
            case "finance_installment_payoff":
                return await handle_installment_payoff(arguments)
            case "finance_upload_attachment":
                return await handle_upload_attachment(arguments)
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


async def handle_manage_wallets(args: dict) -> list[TextContent]:
    action = args["action"]

    if action == "list":
        result = await api_get("/wallets")
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return text_result("No wallets found.")
        lines = ["# Wallets\n"]
        total_net = 0
        for w in items:
            balance = float(w.get("current_balance", 0))
            total_net += balance
            icon = w.get("icon", "")
            private = " 🔒" if w.get("is_private") else ""
            credit = f" (limit: {fmt_amount(w['credit_limit'])})" if w.get("credit_limit") else ""
            lines.append(
                f"  {icon} {w['name']}  {fmt_amount(balance)}  "
                f"[{w['type']}]{credit}{private}  id={w['id'][:8]}"
            )
        lines.append(f"\nNet worth: {fmt_amount(total_net)}")
        return text_result("\n".join(lines))

    if action == "create":
        body: dict[str, Any] = {
            "name": args["name"],
            "type": args["type"],
        }
        for field in ("currency", "initial_balance", "credit_limit", "icon", "color", "sort_order", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await api_post("/wallets", body)
        return text_result(
            f"Wallet created.\n"
            f"ID: {result['id']}\n"
            f"Name: {result['name']} | Type: {result['type']} | Balance: {fmt_amount(result.get('current_balance', 0))}"
        )

    if action == "update":
        wallet_id = args["id"]
        body = {}
        for field in ("name", "icon", "color", "sort_order", "credit_limit", "is_private"):
            if field in args:
                body[field] = args[field]
        result = await api_put(f"/wallets/{wallet_id}", body)
        return text_result(f"Wallet {wallet_id[:8]} updated: {result['name']}")

    if action == "deactivate":
        wallet_id = args["id"]
        result = await api_put(f"/wallets/{wallet_id}", {"is_active": False})
        return text_result(f"Wallet {wallet_id[:8]} deactivated.")

    return text_result(f"Unknown action: {action}")


async def handle_sync_wallet(args: dict) -> list[TextContent]:
    wallet_id = args["wallet_id"]
    body: dict[str, Any] = {
        "synced_balance": args["actual_balance"],
    }
    if "snapshot_type" in args:
        body["snapshot_type"] = args["snapshot_type"]
    if "notes" in args:
        body["notes"] = args["notes"]

    result = await api_post(f"/wallets/{wallet_id}/sync", body)
    diff = float(result.get("difference", 0))
    diff_str = f"{diff:+,.0f}" if diff != 0 else "0 ✅"
    return text_result(
        f"Wallet synced.\n"
        f"Synced balance: {fmt_amount(result.get('synced_balance', 0))}\n"
        f"Calculated balance: {fmt_amount(result.get('calculated_balance', 0))}\n"
        f"Difference: {diff_str}\n"
        f"Snapshot ID: {result.get('id', '-')}"
    )


async def handle_reconcile(args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    if "wallet_id" in args:
        params["wallet_id"] = args["wallet_id"]

    result = await api_get("/wallets/reconcile", params)
    items = result if isinstance(result, list) else result.get("items", [])

    if not items:
        return text_result("No reconciliation data available.")

    lines = ["# Reconciliation Summary\n"]
    for w in items:
        diff = float(w.get("difference", 0))
        status = "✅" if abs(diff) < 1 else f"⚠️ {diff:+,.0f}"
        lines.append(
            f"  {w['wallet_name']}  balance: {fmt_amount(w.get('current_balance', 0))}  "
            f"last sync: {w.get('last_synced_at', 'never')[:10]}  {status}"
        )

    return text_result("\n".join(lines))


async def handle_transfer(args: dict) -> list[TextContent]:
    body: dict[str, Any] = {
        "from_wallet_id": args["from_wallet_id"],
        "to_wallet_id": args["to_wallet_id"],
        "amount": args["amount"],
    }
    for field in ("description", "fee", "transacted_at"):
        if field in args:
            body[field] = args[field]

    result = await api_post("/transfers", body)
    return text_result(
        f"Transfer completed.\n"
        f"From: {result.get('from_wallet', args['from_wallet_id'][:8])}\n"
        f"To: {result.get('to_wallet', args['to_wallet_id'][:8])}\n"
        f"Amount: {fmt_amount(args['amount'])}"
        + (f"\nFee: {fmt_amount(args['fee'])}" if args.get("fee") else "")
    )


async def handle_add_installment(args: dict) -> list[TextContent]:
    body: dict[str, Any] = {
        "description": args["description"],
        "total_amount": args["total_amount"],
        "num_installments": args["num_installments"],
        "wallet_id": args["wallet_id"],
        "payment_method": args["payment_method"],
        "start_date": args["start_date"],
    }
    for field in (
        "payment_detail", "merchant", "category_id", "billing_day",
        "interest_rate", "fee_type", "fee_per_installment", "is_private",
    ):
        if field in args:
            body[field] = args[field]

    result = await api_post("/installments", body)
    per = float(result.get("installment_amount", 0))
    return text_result(
        f"Installment plan created.\n"
        f"ID: {result['id']}\n"
        f"Description: {result['description']}\n"
        f"Total: {fmt_amount(result['total_amount'])} → {result['num_installments']} installments × {fmt_amount(per)}\n"
        f"Start: {result['start_date']} | Wallet: {result.get('wallet_id', '-')[:8]}\n"
        f"Auto-generated {result['num_installments']} scheduled transactions."
    )


async def handle_list_installments(args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    if "status" in args:
        params["status"] = args["status"]
    params["page"] = str(args.get("page", 1))
    params["page_size"] = str(args.get("page_size", 20))

    result = await api_get("/installments", params)
    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        return text_result("No installment plans found.")

    lines = [f"# Installment Plans ({total} total)\n"]
    for p in items:
        status_icon = {"active": "●", "completed": "✓", "cancelled": "✕"}.get(p.get("status", ""), "?")
        paid = p.get("paid_count", 0)
        total_n = p.get("num_installments", 0)
        progress = f"{paid}/{total_n}" if total_n else "-"
        lines.append(
            f"  {status_icon} {p['description']}  {fmt_amount(p['total_amount'])}  "
            f"progress: {progress}  per: {fmt_amount(p.get('installment_amount', 0))}  "
            f"id={p['id'][:8]}"
        )

    return text_result("\n".join(lines))


async def handle_installment_payoff(args: dict) -> list[TextContent]:
    plan_id = args["id"]
    result = await api_post(f"/installments/{plan_id}/payoff")
    remaining = result.get("remaining_settled", 0)
    return text_result(
        f"Installment {plan_id[:8]} paid off.\n"
        f"Remaining installments settled: {remaining}\n"
        f"Status: completed"
    )


async def handle_upload_attachment(args: dict) -> list[TextContent]:
    txn_id = args["transaction_id"]
    file_path = args["file_path"]
    filename = args.get("filename", os.path.basename(file_path))
    content_type = args.get("content_type", "image/jpeg")

    if not os.path.exists(file_path):
        return text_result(f"File not found: {file_path}")

    result = await api_post_file(
        f"/transactions/{txn_id}/attachments",
        file_path, filename, content_type,
    )
    return text_result(
        f"Attachment uploaded.\n"
        f"ID: {result.get('id', '-')}\n"
        f"Filename: {filename}\n"
        f"Storage key: {result.get('storage_key', '-')}"
    )


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
