#!/usr/bin/env python3
"""Invest MCP Server — portfolio tracking thin adapter over Core API.

8 tools: accounts, positions, trades, portfolio, quotes.
Uses workshop.clients.invest SDK.

Usage:
    python3 mcp/invest/server.py
"""

import asyncio
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.invest import InvestClient

server = Server("workshop-invest")
client = InvestClient()


# ======================== Helpers ========================


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def fmt_amount(v: float | int | str, currency: str = "TWD") -> str:
    return f"{currency} {float(v):,.2f}"


def fmt_pct(v: float | int) -> str:
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="invest_list_accounts",
            description="列出投資帳戶",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="invest_create_account",
            description="新增投資帳戶",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "帳戶名稱"},
                    "broker": {"type": "string", "description": "券商"},
                    "currency": {
                        "type": "string",
                        "default": "TWD",
                        "description": "幣別",
                    },
                    "notes": {"type": "string", "description": "備註"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="invest_account_summary",
            description="查看帳戶摘要（含持倉損益）",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "帳戶 ID",
                    },
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="invest_list_positions",
            description="列出持倉部位",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "篩選特定帳戶",
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="invest_create_position",
            description="新增持倉部位",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "帳戶 ID",
                    },
                    "symbol": {
                        "type": "string",
                        "description": "股票代號（如 2330.TW）",
                    },
                    "exchange": {"type": "string", "description": "交易所"},
                    "asset_type": {
                        "type": "string",
                        "enum": ["stock", "etf", "bond", "fund", "crypto"],
                        "default": "stock",
                    },
                    "shares": {"type": "number", "default": 0},
                    "avg_cost": {"type": "number", "default": 0},
                    "current_price": {"type": "number", "default": 0},
                    "currency": {"type": "string", "default": "TWD"},
                },
                "required": ["account_id", "symbol"],
            },
        ),
        Tool(
            name="invest_create_trade",
            description="新增交易紀錄（買入/賣出/股利/分割）",
            inputSchema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "持倉 ID",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["buy", "sell", "dividend", "split"],
                        "description": "交易類型",
                    },
                    "shares": {"type": "number", "description": "股數"},
                    "price": {"type": "number", "description": "價格"},
                    "fee": {"type": "number", "default": 0, "description": "手續費"},
                    "tax": {"type": "number", "default": 0, "description": "稅金"},
                    "traded_at": {
                        "type": "string",
                        "description": "交易時間 ISO 8601",
                    },
                    "notes": {"type": "string", "description": "備註"},
                },
                "required": ["position_id", "type", "shares", "price", "traded_at"],
            },
        ),
        Tool(
            name="invest_portfolio",
            description="查看投資組合總覽（所有帳戶彙總）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="invest_refresh_quotes",
            description="更新股價報價",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "股票代號列表（空則更新全部）",
                    },
                },
            },
        ),
    ]


# ======================== Handlers ========================


async def handle_list_accounts(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_accounts,
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    if not items:
        return text_result("目前沒有投資帳戶。")
    lines = [f"# 投資帳戶（共 {result.get('total', 0)} 個）\n"]
    for a in items:
        broker = a.get("broker") or "未設定"
        lines.append(f"- **{a['name']}** ({broker}) [{a.get('currency', 'TWD')}]  `{a['id'][:8]}`")
    return text_result("\n".join(lines))


async def handle_create_account(args: dict) -> list[TextContent]:
    body = {"name": args["name"]}
    for f in ("broker", "currency", "notes"):
        if f in args:
            body[f] = args[f]
    result = await to_thread(client.create_account, body)
    return text_result(
        f"帳戶已建立\n"
        f"- 名稱: {result['name']}\n"
        f"- ID: {result['id'][:8]}\n"
        f"- 券商: {result.get('broker', '未設定')}"
    )


async def handle_account_summary(args: dict) -> list[TextContent]:
    result = await to_thread(client.get_account_summary, args["account_id"])
    lines = [
        f"# {result['name']} 帳戶摘要\n",
        f"- 市值: {fmt_amount(result.get('total_market_value', 0))}",
        f"- 成本: {fmt_amount(result.get('total_cost', 0))}",
        f"- 損益: {fmt_amount(result.get('total_gain', 0))} ({fmt_pct(result.get('gain_pct', 0))})",
        f"- 持倉數: {result.get('position_count', 0)}",
    ]
    return text_result("\n".join(lines))


async def handle_list_positions(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_positions,
        account_id=args.get("account_id"),
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    if not items:
        return text_result("目前沒有持倉部位。")
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
    return text_result("\n".join(lines))


async def handle_create_position(args: dict) -> list[TextContent]:
    body = {"account_id": args["account_id"], "symbol": args["symbol"]}
    for f in (
        "exchange",
        "asset_type",
        "shares",
        "avg_cost",
        "current_price",
        "currency",
    ):
        if f in args:
            body[f] = args[f]
    result = await to_thread(client.create_position, body)
    return text_result(
        f"持倉已建立\n"
        f"- 代號: {result['symbol']}\n"
        f"- ID: {result['id'][:8]}\n"
        f"- 股數: {result.get('shares', 0)}"
    )


async def handle_create_trade(args: dict) -> list[TextContent]:
    body = {
        "position_id": args["position_id"],
        "type": args["type"],
        "shares": args["shares"],
        "price": args["price"],
        "traded_at": args["traded_at"],
    }
    for f in ("fee", "tax", "notes", "currency"):
        if f in args:
            body[f] = args[f]
    result = await to_thread(client.create_trade, body)
    total = result.get("total_amount", 0)
    return text_result(
        f"交易已記錄\n"
        f"- 類型: {args['type']}\n"
        f"- {args['shares']} 股 @ {fmt_amount(args['price'])}\n"
        f"- 總額: {fmt_amount(total)}\n"
        f"- ID: {result['id'][:8]}"
    )


async def handle_portfolio(args: dict) -> list[TextContent]:
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
    return text_result("\n".join(lines))


async def handle_refresh_quotes(args: dict) -> list[TextContent]:
    symbols = args.get("symbols", [])
    result = await to_thread(client.refresh_quotes, symbols)
    if not result:
        return text_result("無報價可更新。")
    lines = ["# 報價已更新\n"]
    for q in result:
        change = q.get("change_pct")
        change_str = f" ({fmt_pct(change)})" if change is not None else ""
        lines.append(
            f"- **{q['symbol']}**: {fmt_amount(q['price'], q.get('currency', 'TWD'))}{change_str}"
        )
    return text_result("\n".join(lines))


# ======================== Dispatcher ========================

HANDLERS = {
    "invest_list_accounts": handle_list_accounts,
    "invest_create_account": handle_create_account,
    "invest_account_summary": handle_account_summary,
    "invest_list_positions": handle_list_positions,
    "invest_create_position": handle_create_position,
    "invest_create_trade": handle_create_trade,
    "invest_portfolio": handle_portfolio,
    "invest_refresh_quotes": handle_refresh_quotes,
}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return text_result(f"未知工具: {name}")
    try:
        return await handler(arguments)
    except APIError as e:
        return text_result(f"API 錯誤: {e}")
    except APIConnectionError as e:
        return text_result(f"連線失敗: {e}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
