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

from mcp.server.fastmcp import FastMCP
from workshop.clients.finance import FinanceClient
from workshop.mcp_helpers import build_body, fmt_amount, mcp_error_handler

mcp = FastMCP("workshop-finance-wallet")
client = FinanceClient()


# ======================== Tool Implementations ========================


@mcp.tool()
@mcp_error_handler("Finance")
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
        body = build_body(
            {"name": name, "type": type, "is_private": is_private},
            currency=currency,
            initial_balance=initial_balance,
            credit_limit=credit_limit,
            icon=icon,
            color=color,
            sort_order=sort_order,
        )
        result = await to_thread(client.create_wallet, body)
        return (
            f"Wallet created.\n"
            f"ID: {result['id']}\n"
            f"Name: {result['name']} | Type: {result['type']} | Balance: {fmt_amount(result.get('current_balance', 0))}"
        )

    if action == "update":
        body = build_body(
            {"is_private": is_private},
            name=name,
            icon=icon,
            color=color,
            sort_order=sort_order,
            credit_limit=credit_limit,
        )
        result = await to_thread(client.update_wallet, id, body)
        return f"Wallet {id[:8]} updated: {result['name']}"

    if action == "deactivate":
        result = await to_thread(client.update_wallet, id, {"is_active": False})
        return f"Wallet {id[:8]} deactivated."

    return f"Unknown action: {action}"


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_sync_wallet(
    wallet_id: str,
    actual_balance: float,
    snapshot_type: str = "reconciliation",
    notes: str = "",
) -> str:
    """同步錢包餘額，產生 snapshot（對帳用）"""
    body = build_body(
        {"synced_balance": actual_balance},
        snapshot_type=snapshot_type,
        notes=notes,
    )
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


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_reconcile(wallet_id: str = "") -> str:
    """錢包對帳摘要（各錢包系統餘額 vs 差額趨勢）"""
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


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_snapshot_history(
    wallet_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """錢包快照歷史（版本時間軸）"""
    result = await to_thread(client.list_snapshots, wallet_id, page=page, page_size=page_size)
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No snapshots found for this wallet."
    lines = [f"# Snapshot History ({total} total)\n"]
    for s in items:
        diff = float(s.get("difference", 0))
        diff_str = f"  diff: {diff:+,.0f}" if abs(diff) >= 1 else ""
        batch = " [global]" if s.get("batch_id") else ""
        lines.append(
            f"  v{s.get('version', '?')}  {fmt_amount(s.get('synced_balance', 0))}"
            f"  [{s.get('synced_at', '?')}]{batch}{diff_str}"
        )
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_snapshot_diff(
    wallet_id: str,
    from_version: int,
    to_version: int,
) -> str:
    """RPG 式差分比較（兩個快照版本間的餘額變化）"""
    result = await to_thread(client.snapshot_diff, wallet_id, from_version, to_version)
    delta = float(result.get("balance_delta", 0))
    pct = result.get("delta_pct", 0)
    arrow = "▲" if delta > 0 else "▼" if delta < 0 else "─"
    return (
        f"# Snapshot Diff: v{from_version} → v{to_version}\n\n"
        f"From:   {fmt_amount(result.get('from_synced_balance', 0))}\n"
        f"To:     {fmt_amount(result.get('to_synced_balance', 0))}\n"
        f"Delta:  {arrow} {fmt_amount(abs(delta))} ({pct:+.1f}%)\n"
        f"Period: {result.get('period_days', 0)} days"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_gap_analysis(
    wallet_id: str,
    from_version: int,
    to_version: int,
) -> str:
    """夾擊對帳：快照差分 vs 交易累加 → 找出缺口"""
    result = await to_thread(client.gap_analysis, wallet_id, from_version, to_version)
    gap = float(result.get("gap", 0))
    reconciled = result.get("is_reconciled", False)
    status = "RECONCILED" if reconciled else f"GAP: {fmt_amount(abs(gap))}"
    txns = result.get("transactions", [])
    lines = [
        f"# Gap Analysis: v{from_version} → v{to_version}\n",
        f"Snapshot delta:  {fmt_amount(result.get('snapshot_delta', 0))}",
        f"Transaction sum: {fmt_amount(result.get('transaction_sum', 0))}",
        f"Gap:             {fmt_amount(gap)}",
        f"Status:          {status}",
    ]
    if txns:
        lines.append(f"\nTransactions in period ({len(txns)}):")
        for t in txns[:10]:
            icon = {"income": "+", "expense": "-", "transfer": "~"}.get(t.get("type", ""), "?")
            desc = t.get("description") or t.get("merchant") or "-"
            lines.append(f"  {icon} {fmt_amount(t.get('amount', 0))}  {desc[:40]}")
        if len(txns) > 10:
            lines.append(f"  ... and {len(txns) - 10} more")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_global_snapshot() -> str:
    """全域快照 — 所有 active 錢包一次存檔（RPG 存檔點）"""
    result = await to_thread(client.create_global_snapshot)
    batch_id = result.get("batch_id", "?")
    count = result.get("snapshot_count", 0)
    net = float(result.get("total_net_worth", 0))
    return (
        f"Global snapshot created.\n"
        f"Batch ID: {batch_id}\n"
        f"Wallets:  {count}\n"
        f"Net worth: {fmt_amount(net)}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_transfer(
    from_wallet_id: str,
    to_wallet_id: str,
    amount: float,
    description: str = "",
    fee: float = 0,
    transacted_at: str = "",
) -> str:
    """錢包間轉帳"""
    body = build_body(
        {"from_wallet_id": from_wallet_id, "to_wallet_id": to_wallet_id, "amount": amount},
        description=description,
        fee=fee or None,
        transacted_at=transacted_at,
    )
    await to_thread(client.transfer, body)
    return (
        f"Transfer completed.\n"
        f"From: {from_wallet_id[:8]} → To: {to_wallet_id[:8]}\n"
        f"Amount: {fmt_amount(amount)}"
        + (f"\nFee: {fmt_amount(fee)}" if fee else "")
    )


@mcp.tool()
@mcp_error_handler("Finance")
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
    body = build_body(
        {
            "description": description,
            "total_amount": total_amount,
            "num_installments": num_installments,
            "wallet_id": wallet_id,
            "payment_method": payment_method,
            "start_date": start_date,
            "is_private": is_private,
        },
        payment_detail=payment_detail,
        merchant=merchant,
        category_id=category_id,
        billing_day=billing_day,
        interest_rate=interest_rate or None,
        fee_type=fee_type if fee_type and fee_type != "none" else None,
        fee_per_installment=fee_per_installment or None,
    )
    result = await to_thread(client.create_installment, body)
    per = float(result.get("installment_amount", 0))
    return (
        f"Installment plan created.\n"
        f"ID: {result['id']}\n"
        f"Description: {result['description']}\n"
        f"Total: {fmt_amount(result['total_amount'])} -> {result['num_installments']} x {fmt_amount(per)}\n"
        f"Start: {result['start_date']}"
    )


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_list_installments(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """列出分期付款計畫"""
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


@mcp.tool()
@mcp_error_handler("Finance")
async def finance_installment_payoff(id: str) -> str:
    """分期提前還款（將所有剩餘期數標記為 completed）"""
    await to_thread(client.update_installment, id, {"status": "completed"})
    return f"Installment {id[:8]} paid off. Status: completed"


@mcp.tool()
@mcp_error_handler("Finance")
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

    return f"Attachment uploaded.\nID: {result.get('id', '-')}\nFilename: {resolved_filename}"


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()
