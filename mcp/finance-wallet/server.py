#!/usr/bin/env python3
"""Finance Wallet MCP Server — wallet + installment adapter over FinanceClient SDK.

8 tools: wallet CRUD, sync, reconcile, transfer, installment CRUD, payoff, attachment.

Usage:
    python3 mcp/finance-wallet/server.py

Configure in ~/.claude.json:
    "workshop-finance-wallet": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/finance-wallet/server.py"],
        "env": {}
    }
"""

import os
from asyncio import to_thread
from typing import Any

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.finance import FinanceClient

mcp = FastMCP("workshop-finance-wallet")
client = FinanceClient()


def fmt_amount(amount: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(amount):,.0f}"


# ======================== Tool Implementations ========================


@mcp.tool()
async def finance_manage_wallets(
    action: str,
    id: str = "",
    name: str = "",
    type: str = "",
    currency: str = "TWD",
    initial_balance: float | None = None,
    credit_limit: float | None = None,
    icon: str = "",
    color: str = "",
    sort_order: int | None = None,
    is_private: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """錢包管理（列表/新增/編輯/停用）"""
    try:
        if action == "list":
            page_size = min(page_size, 50)
            result = await to_thread(client.list_wallets, page=page, page_size=page_size)
            items = result if isinstance(result, list) else result.get("items", [])
            total_count = result.get("total", len(items)) if isinstance(result, dict) else len(items)
            if not items:
                return "No wallets found."
            lines = [f"# Wallets (showing {len(items)} of {total_count}, page {page})\n"]
            total_net = 0
            for w in items:
                balance = float(w.get("current_balance", 0))
                total_net += balance
                icon_val = w.get("icon", "")
                private = " 🔒" if w.get("is_private") else ""
                credit = f" (limit: {fmt_amount(w['credit_limit'])})" if w.get("credit_limit") else ""
                lines.append(
                    f"  {icon_val} {w['name']}  {fmt_amount(balance)}  "
                    f"[{w['type']}]{credit}{private}  id={w['id'][:8]}"
                )
            lines.append(f"\nNet worth (this page): {fmt_amount(total_net)}")
            lines.append(f"total_count: {total_count}")
            return "\n".join(lines)

        if action == "create":
            body: dict[str, Any] = {"name": name, "type": type}
            if currency:
                body["currency"] = currency
            if initial_balance is not None:
                body["initial_balance"] = initial_balance
            if credit_limit is not None:
                body["credit_limit"] = credit_limit
            if icon:
                body["icon"] = icon
            if color:
                body["color"] = color
            if sort_order is not None:
                body["sort_order"] = sort_order
            body["is_private"] = is_private
            result = await to_thread(client.create_wallet, body)
            return (
                f"Wallet created.\n"
                f"ID: {result['id']}\n"
                f"Name: {result['name']} | Type: {result['type']} | Balance: {fmt_amount(result.get('current_balance', 0))}"
            )

        if action == "update":
            body = {}
            if name:
                body["name"] = name
            if icon:
                body["icon"] = icon
            if color:
                body["color"] = color
            if sort_order is not None:
                body["sort_order"] = sort_order
            if credit_limit is not None:
                body["credit_limit"] = credit_limit
            body["is_private"] = is_private
            result = await to_thread(client.update_wallet, id, body)
            return f"Wallet {id[:8]} updated: {result['name']}"

        if action == "deactivate":
            result = await to_thread(client.update_wallet, id, {"is_active": False})
            return f"Wallet {id[:8]} deactivated."

        return f"Unknown action: {action}"
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_sync_wallet(
    wallet_id: str,
    actual_balance: float,
    snapshot_type: str = "reconciliation",
    notes: str = "",
) -> str:
    """同步錢包餘額，產生 snapshot（對帳用）"""
    try:
        body: dict[str, Any] = {"synced_balance": actual_balance}
        if snapshot_type:
            body["snapshot_type"] = snapshot_type
        if notes:
            body["notes"] = notes

        result = await to_thread(client.sync_wallet, wallet_id, body)
        diff = float(result.get("difference", 0))
        diff_str = f"{diff:+,.0f}" if diff != 0 else "0"
        return (
            f"Wallet synced.\n"
            f"Synced balance: {fmt_amount(result.get('synced_balance', 0))}\n"
            f"Calculated balance: {fmt_amount(result.get('calculated_balance', 0))}\n"
            f"Difference: {diff_str}\n"
            f"Snapshot ID: {result.get('id', '-')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_reconcile(wallet_id: str = "") -> str:
    """錢包對帳摘要（各錢包系統餘額 vs 差額趨勢）"""
    try:
        if wallet_id:
            result = await to_thread(client.reconcile_wallet, wallet_id)
        else:
            result = await to_thread(client.list_wallets)
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return "No reconciliation data available."
        lines = ["# Reconciliation Summary\n"]
        for w in items:
            diff = float(w.get("difference", 0))
            status = "OK" if abs(diff) < 1 else f"diff: {diff:+,.0f}"
            lines.append(
                f"  {w.get('wallet_name', w.get('name', '?'))}  "
                f"balance: {fmt_amount(w.get('current_balance', 0))}  {status}"
            )
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_transfer(
    from_wallet_id: str,
    to_wallet_id: str,
    amount: float,
    description: str = "",
    fee: float = 0,
    transacted_at: str = "",
) -> str:
    """錢包間轉帳"""
    try:
        body: dict[str, Any] = {
            "from_wallet_id": from_wallet_id,
            "to_wallet_id": to_wallet_id,
            "amount": amount,
        }
        if description:
            body["description"] = description
        if fee:
            body["fee"] = fee
        if transacted_at:
            body["transacted_at"] = transacted_at

        await to_thread(client.transfer, body)
        return (
            f"Transfer completed.\n"
            f"From: {from_wallet_id[:8]} → To: {to_wallet_id[:8]}\n"
            f"Amount: {fmt_amount(amount)}"
            + (f"\nFee: {fmt_amount(fee)}" if fee else "")
        )
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_add_installment(
    description: str,
    total_amount: float,
    num_installments: int,
    wallet_id: str,
    payment_method: str,
    start_date: str,
    payment_detail: str = "",
    merchant: str = "",
    category_id: str = "",
    billing_day: int | None = None,
    interest_rate: float = 0,
    fee_type: str = "none",
    fee_per_installment: float = 0,
    is_private: bool = False,
) -> str:
    """新增分期付款計畫（自動產生 scheduled transactions）"""
    try:
        body: dict[str, Any] = {
            "description": description,
            "total_amount": total_amount,
            "num_installments": num_installments,
            "wallet_id": wallet_id,
            "payment_method": payment_method,
            "start_date": start_date,
        }
        if payment_detail:
            body["payment_detail"] = payment_detail
        if merchant:
            body["merchant"] = merchant
        if category_id:
            body["category_id"] = category_id
        if billing_day is not None:
            body["billing_day"] = billing_day
        if interest_rate:
            body["interest_rate"] = interest_rate
        if fee_type and fee_type != "none":
            body["fee_type"] = fee_type
        if fee_per_installment:
            body["fee_per_installment"] = fee_per_installment
        body["is_private"] = is_private

        result = await to_thread(client.create_installment, body)
        per = float(result.get("installment_amount", 0))
        return (
            f"Installment plan created.\n"
            f"ID: {result['id']}\n"
            f"Description: {result['description']}\n"
            f"Total: {fmt_amount(result['total_amount'])} -> {result['num_installments']} x {fmt_amount(per)}\n"
            f"Start: {result['start_date']}"
        )
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_list_installments(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """列出分期付款計畫"""
    try:
        result = await to_thread(
            client.list_installments,
            status=status or None,
            page=page,
            page_size=page_size,
        )
        items = result.get("items", [])
        total = result.get("total", 0)
        if not items:
            return "No installment plans found."
        lines = [f"# Installment Plans ({total} total)\n"]
        for p in items:
            status_icon = {"active": "O", "completed": "V", "cancelled": "X"}.get(
                p.get("status", ""), "?"
            )
            paid = p.get("paid_count", 0)
            total_n = p.get("num_installments", 0)
            lines.append(
                f"  [{status_icon}] {p['description']}  {fmt_amount(p['total_amount'])}  "
                f"progress: {paid}/{total_n}  per: {fmt_amount(p.get('installment_amount', 0))}  "
                f"id={p['id'][:8]}"
            )
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_installment_payoff(id: str) -> str:
    """分期提前還款（將所有剩餘期數標記為 completed）"""
    try:
        await to_thread(client.update_installment, id, {"status": "completed"})
        return f"Installment {id[:8]} paid off. Status: completed"
    except (APIError, APIConnectionError) as e:
        return f"Finance API error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def finance_upload_attachment(
    transaction_id: str,
    file_path: str,
    filename: str = "",
    content_type: str = "image/jpeg",
) -> str:
    """上傳交易附件照片"""
    # Attachment upload requires multipart — keep raw httpx for file upload
    import httpx

    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    resolved_filename = filename or os.path.basename(file_path)

    try:
        with open(file_path, "rb") as f:
            data = f.read()
        files = {"file": (resolved_filename, data, content_type)}
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                f"{client.prefix}/transactions/{transaction_id}/attachments",
                files=files,
                params={"space_id": client.space_id},
            )
            resp.raise_for_status()
            result = resp.json()
    except httpx.ConnectError as e:
        return f"Connection error uploading attachment: {e}"
    except httpx.TimeoutException as e:
        return f"Timeout uploading attachment: {e}"
    except httpx.HTTPStatusError as e:
        return f"Upload failed ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

    return f"Attachment uploaded.\nID: {result.get('id', '-')}\nFilename: {resolved_filename}"


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()
