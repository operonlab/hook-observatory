#!/usr/bin/env python3
"""Invest MCP Server — portfolio tracking thin adapter over Core API.

8 tools: accounts, positions, trades, portfolio, quotes.
Uses workshop.clients.invest SDK.

Usage:
    python3 mcp/invest/server.py
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.invest import InvestClient

mcp = FastMCP("workshop-invest")
client = InvestClient()


# ======================== Helpers ========================


def fmt_amount(v: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(v):,.2f}"


def fmt_pct(v: float | int) -> str:
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


# ======================== Tools ========================


@mcp.tool()
async def invest_list_accounts(page: int = 1, page_size: int = 20) -> str:
    """列出投資帳戶"""
    try:
        result = await to_thread(client.list_accounts, page=page, page_size=page_size)
        items = result.get("items", [])
        if not items:
            return "目前沒有投資帳戶。"
        lines = [f"# 投資帳戶（共 {result.get('total', 0)} 個）\n"]
        for a in items:
            broker = a.get("broker") or "未設定"
            lines.append(f"- **{a['name']}** ({broker}) [{a.get('currency', 'TWD')}]  `{a['id'][:8]}`")
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_create_account(
    name: str,
    broker: str = "",
    currency: str = "TWD",
    notes: str = "",
) -> str:
    """新增投資帳戶"""
    try:
        body: dict = {"name": name}
        if broker:
            body["broker"] = broker
        if currency:
            body["currency"] = currency
        if notes:
            body["notes"] = notes
        result = await to_thread(client.create_account, body)
        return (
            f"帳戶已建立\n"
            f"- 名稱: {result['name']}\n"
            f"- ID: {result['id'][:8]}\n"
            f"- 券商: {result.get('broker', '未設定')}"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_account_summary(account_id: str) -> str:
    """查看帳戶摘要（含持倉損益）"""
    try:
        result = await to_thread(client.get_account_summary, account_id)
        lines = [
            f"# {result['name']} 帳戶摘要\n",
            f"- 市值: {fmt_amount(result.get('total_market_value', 0))}",
            f"- 成本: {fmt_amount(result.get('total_cost', 0))}",
            f"- 損益: {fmt_amount(result.get('total_gain', 0))} ({fmt_pct(result.get('gain_pct', 0))})",
            f"- 持倉數: {result.get('position_count', 0)}",
        ]
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_list_positions(
    account_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """列出持倉部位"""
    try:
        result = await to_thread(
            client.list_positions,
            account_id=account_id or None,
            page=page,
            page_size=page_size,
        )
        items = result.get("items", [])
        if not items:
            return "目前沒有持倉部位。"
        lines = [f"# 持倉部位（共 {result.get('total', 0)} 個）\n"]
        for p in items:
            gain = p.get("unrealized_gain", 0)
            pct = p.get("gain_pct", 0)
            lines.append(
                f"- **{p['symbol']}** {p.get('shares', 0)} 股"
                f" @ {fmt_amount(p.get('current_price', 0))}"
                f" | 損益 {fmt_amount(gain)} ({fmt_pct(pct)})"
                f"  `{p['id'][:8]}`"
            )
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_create_position(
    account_id: str,
    symbol: str,
    exchange: str = "",
    asset_type: str = "stock",
    shares: float = 0,
    avg_cost: float = 0,
    current_price: float = 0,
    currency: str = "TWD",
) -> str:
    """新增持倉部位"""
    try:
        body: dict = {"account_id": account_id, "symbol": symbol}
        if exchange:
            body["exchange"] = exchange
        if asset_type:
            body["asset_type"] = asset_type
        if shares:
            body["shares"] = shares
        if avg_cost:
            body["avg_cost"] = avg_cost
        if current_price:
            body["current_price"] = current_price
        if currency:
            body["currency"] = currency
        result = await to_thread(client.create_position, body)
        return (
            f"持倉已建立\n"
            f"- 代號: {result['symbol']}\n"
            f"- ID: {result['id'][:8]}\n"
            f"- 股數: {result.get('shares', 0)}"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_create_trade(
    position_id: str,
    type: str,
    shares: float,
    price: float,
    traded_at: str,
    fee: float = 0,
    tax: float = 0,
    notes: str = "",
) -> str:
    """新增交易紀錄（買入/賣出/股利/分割）"""
    try:
        body: dict = {
            "position_id": position_id,
            "type": type,
            "shares": shares,
            "price": price,
            "traded_at": traded_at,
        }
        if fee:
            body["fee"] = fee
        if tax:
            body["tax"] = tax
        if notes:
            body["notes"] = notes
        result = await to_thread(client.create_trade, body)
        total = result.get("total_amount", 0)
        return (
            f"交易已記錄\n"
            f"- 類型: {type}\n"
            f"- {shares} 股 @ {fmt_amount(price)}\n"
            f"- 總額: {fmt_amount(total)}\n"
            f"- ID: {result['id'][:8]}"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_portfolio() -> str:
    """查看投資組合總覽（所有帳戶彙總）"""
    try:
        result = await to_thread(client.get_portfolio)
        lines = [
            "# 投資組合總覽\n",
            f"- 總市值: {fmt_amount(result.get('total_market_value', 0))}",
            f"- 總成本: {fmt_amount(result.get('total_cost', 0))}",
            f"- 總損益: {fmt_amount(result.get('total_gain', 0))}"
            f" ({fmt_pct(result.get('gain_pct', 0))})",
            f"- 帳戶數: {result.get('account_count', 0)}",
            f"- 持倉數: {result.get('position_count', 0)}",
        ]
        accounts = result.get("accounts", [])
        if accounts:
            lines.append("\n## 帳戶明細\n")
            for a in accounts:
                gain = a.get("total_gain", 0)
                lines.append(
                    f"- **{a['name']}**: "
                    f"{fmt_amount(a.get('total_market_value', 0))}"
                    f" (損益 {fmt_amount(gain)}, {fmt_pct(a.get('gain_pct', 0))})"
                )
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def invest_refresh_quotes(symbols: list[str] | None = None) -> str:
    """更新股價報價"""
    try:
        result = await to_thread(client.refresh_quotes, symbols or [])
        if not result:
            return "無報價可更新。"
        lines = ["# 報價已更新\n"]
        for q in result:
            change = q.get("change_pct")
            change_str = f" ({fmt_pct(change)})" if change is not None else ""
            lines.append(
                f"- **{q['symbol']}**: {fmt_amount(q['price'], q.get('currency', 'TWD'))}{change_str}"
            )
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
