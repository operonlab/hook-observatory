#!/Users/joneshong/.local/bin/python3
"""Invest CLI — command-line interface for Invest Core API.

Uses the shared workshop SDK client (InvestClient).

Usage:
    invest accounts list [--json]
    invest accounts get <id> [--json]
    invest accounts create --name NAME [--broker B] [--currency C] [--json]
    invest accounts summary <id> [--json]
    invest positions list [--account A] [--json]
    invest positions create --account A --symbol S --shares N --avg-cost C --price P [--json]
    invest positions update-price <id> --price P [--json]
    invest trades list [--position P] [--json]
    invest trades create --position P --type T --shares N --price P [--fee F] [--tax T] [--json]
    invest portfolio summary [--json]
    invest quotes refresh [--symbols S,S,...] [--json]

Symlink: ln -sf ~/workshop/core/cli/invest.py ~/.local/bin/invest
"""

import argparse

from cli.cli_helpers import err, fmt_date, json_out
from cli.cli_utils import resolve_text_arg
from sdk_client._base import APIConnectionError, APIError
from sdk_client.invest import InvestClient


def _client():
    return InvestClient()


def fmt_amount(v):
    """Format number with commas and 2 decimals."""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def fmt_pct(v):
    """Format percentage with +/- sign."""
    try:
        val = float(v)
        return f"{val:+.2f}%"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def cmd_account_list(args):
    client = _client()
    try:
        result = client.list_accounts()
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Accounts ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for a in items:
            broker = a.get("broker") or "-"
            currency = a.get("currency", "TWD")
            print(f"  {a['name']:<25s}  broker: {broker:<15s}  {currency}  id={a['id'][:8]}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_account_get(args):
    client = _client()
    try:
        a = client.get_account(args.id)
        if json_out(a, args):
            return
        print(f"Account: {a['id']}")
        print(f"  Name:     {a.get('name')}")
        print(f"  Broker:   {a.get('broker', '-')}")
        print(f"  Currency: {a.get('currency', '-')}")
        print(f"  Notes:    {a.get('notes', '-')}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_account_create(args):
    client = _client()
    try:
        data = {"name": args.name}
        if args.broker:
            data["broker"] = args.broker
        if args.currency:
            data["currency"] = args.currency
        notes = resolve_text_arg(args.notes)
        if notes:
            data["notes"] = notes
        result = client.create_account(data)
        if json_out(result, args):
            return
        print(f"Account created: {result['id']}")
        print(f"  {result['name']} | {result.get('broker', '-')} | {result.get('currency', 'TWD')}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_account_summary(args):
    client = _client()
    try:
        s = client.get_account_summary(args.id)
        if json_out(s, args):
            return
        print(f"Account Summary: {s.get('name')}  (id={s['id'][:8]})\n")
        print(f"  Market Value:  {fmt_amount(s.get('total_market_value', 0))}")
        print(f"  Total Cost:    {fmt_amount(s.get('total_cost', 0))}")
        gain_str = f"{fmt_amount(s.get('total_gain', 0))}  ({fmt_pct(s.get('gain_pct', 0))})"
        print(f"  Total Gain:    {gain_str}")
        print(f"  Positions:     {s.get('position_count', 0)}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------


def cmd_position_list(args):
    client = _client()
    try:
        result = client.list_positions(account_id=args.account)
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Positions ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for p in items:
            gain = p.get("unrealized_gain", 0)
            gain_pct = p.get("gain_pct", 0)
            print(
                f"  {p['symbol']:<8s}  shares: {fmt_amount(p.get('shares', 0)):>12s}"
                f"  avg: {fmt_amount(p.get('avg_cost', 0)):>10s}"
                f"  price: {fmt_amount(p.get('current_price', 0)):>10s}"
                f"  gain: {fmt_amount(gain):>12s} ({fmt_pct(gain_pct)})"
                f"  id={p['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_position_create(args):
    client = _client()
    try:
        data = {
            "account_id": args.account,
            "symbol": args.symbol,
            "shares": args.shares,
            "avg_cost": args.avg_cost,
            "current_price": args.price,
        }
        if args.exchange:
            data["exchange"] = args.exchange
        if args.asset_type:
            data["asset_type"] = args.asset_type
        if args.currency:
            data["currency"] = args.currency
        notes = resolve_text_arg(args.notes)
        if notes:
            data["notes"] = notes
        result = client.create_position(data)
        if json_out(result, args):
            return
        print(f"Position created: {result['id']}")
        print(
            f"  {result['symbol']}  shares: {fmt_amount(result.get('shares', 0))}"
            f"  avg_cost: {fmt_amount(result.get('avg_cost', 0))}"
        )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_position_update_price(args):
    client = _client()
    try:
        result = client.update_position_price(args.id, args.price)
        if json_out(result, args):
            return
        print(f"Position {args.id[:8]} price updated to {fmt_amount(args.price)}")
        gain = fmt_amount(result.get("unrealized_gain", 0))
        pct = fmt_pct(result.get("gain_pct", 0))
        gain_str = f"{gain}  ({pct})"
        print(f"  Gain: {gain_str}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# trades
# ---------------------------------------------------------------------------


def cmd_trade_list(args):
    client = _client()
    try:
        result = client.list_trades(position_id=args.position)
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Trades ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            icon = {"buy": "+", "sell": "-", "dividend": "$", "split": "~"}.get(
                t.get("type", ""), "?"
            )
            date = fmt_date(t.get("traded_at"))
            print(
                f"  [{icon}] {t.get('type', '?'):<8s}"
                f"  shares: {fmt_amount(t.get('shares', 0)):>12s}"
                f"  price: {fmt_amount(t.get('price', 0)):>10s}"
                f"  total: {fmt_amount(t.get('total_amount', 0)):>12s}"
                f"  [{date}]  id={t['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_trade_create(args):
    client = _client()
    try:
        data = {
            "position_id": args.position,
            "type": args.type,
            "shares": args.shares,
            "price": args.price,
            "traded_at": args.traded_at,
        }
        if args.fee is not None:
            data["fee"] = args.fee
        if args.tax is not None:
            data["tax"] = args.tax
        if args.currency:
            data["currency"] = args.currency
        notes = resolve_text_arg(args.notes)
        if notes:
            data["notes"] = notes
        result = client.create_trade(data)
        if json_out(result, args):
            return
        print(f"Trade created: {result['id']}")
        print(
            f"  {result.get('type')}  shares: {fmt_amount(result.get('shares', 0))}"
            f"  @ {fmt_amount(result.get('price', 0))}"
            f"  total: {fmt_amount(result.get('total_amount', 0))}"
        )
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# portfolio
# ---------------------------------------------------------------------------


def cmd_portfolio(args):
    client = _client()
    try:
        p = client.get_portfolio()
        if json_out(p, args):
            return
        print("Portfolio Summary\n")
        print(f"  Market Value:  {fmt_amount(p.get('total_market_value', 0))}")
        print(f"  Total Cost:    {fmt_amount(p.get('total_cost', 0))}")
        gain_str = f"{fmt_amount(p.get('total_gain', 0))}  ({fmt_pct(p.get('gain_pct', 0))})"
        print(f"  Total Gain:    {gain_str}")
        print(f"  Accounts:      {p.get('account_count', 0)}")
        print(f"  Positions:     {p.get('position_count', 0)}")
        accounts = p.get("accounts", [])
        if accounts:
            print("\n  By Account:")
            for a in accounts:
                print(
                    f"    {a.get('name', '?'):<25s}"
                    f"  {fmt_amount(a.get('total_market_value', 0)):>14s}"
                    f"  gain: {fmt_pct(a.get('gain_pct', 0))}"
                )
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# quotes
# ---------------------------------------------------------------------------


def cmd_quotes_refresh(args):
    client = _client()
    try:
        symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else []
        result = client.refresh_quotes(symbols)
        if json_out(result, args):
            return
        quotes = result if isinstance(result, list) else []
        print(f"Quotes refreshed ({len(quotes)} symbols)\n")
        for q in quotes:
            change = q.get("change_pct")
            change_str = fmt_pct(change) if change is not None else "n/a"
            print(
                f"  {q.get('symbol', '?'):<8s}"
                f"  price: {fmt_amount(q.get('price', 0)):>10s}"
                f"  change: {change_str:>8s}"
                f"  [{fmt_date(q.get('quoted_at'))}]"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(prog="invest", description="Invest CLI for Workshop Core API")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- accounts --
    acc_parser = sub.add_parser("accounts", aliases=["acc"], help="Account management")
    acc_sub = acc_parser.add_subparsers(dest="action", required=True)

    acc_list = acc_sub.add_parser("list", help="List investment accounts")
    acc_list.set_defaults(func=cmd_account_list)

    acc_get = acc_sub.add_parser("get", help="Get account by ID")
    acc_get.add_argument("id", help="Account ID")
    acc_get.set_defaults(func=cmd_account_get)

    acc_create = acc_sub.add_parser("create", help="Create an investment account")
    acc_create.add_argument("--name", required=True, help="Account name")
    acc_create.add_argument("--broker", help="Broker name")
    acc_create.add_argument("--currency", default="TWD", help="Currency code (default: TWD)")
    acc_create.add_argument("--notes", help="Free-form notes")
    acc_create.set_defaults(func=cmd_account_create)

    acc_summary = acc_sub.add_parser("summary", help="Show account with positions and gain/loss")
    acc_summary.add_argument("id", help="Account ID")
    acc_summary.set_defaults(func=cmd_account_summary)

    # -- positions --
    pos_parser = sub.add_parser("positions", aliases=["pos"], help="Position management")
    pos_sub = pos_parser.add_subparsers(dest="action", required=True)

    pos_list = pos_sub.add_parser("list", help="List positions")
    pos_list.add_argument("--account", "-a", help="Filter by account ID")
    pos_list.set_defaults(func=cmd_position_list)

    pos_create = pos_sub.add_parser("create", help="Create a position")
    pos_create.add_argument("--account", "-a", required=True, help="Account ID")
    pos_create.add_argument("--symbol", "-s", required=True, help="Ticker symbol")
    pos_create.add_argument("--shares", type=float, required=True, help="Number of shares")
    pos_create.add_argument(
        "--avg-cost", type=float, required=True, dest="avg_cost", help="Average cost per share"
    )
    pos_create.add_argument("--price", type=float, required=True, help="Current market price")
    pos_create.add_argument("--exchange", help="Exchange code")
    pos_create.add_argument(
        "--asset-type",
        dest="asset_type",
        default="stock",
        choices=["stock", "etf", "fund", "bond", "crypto", "other"],
        help="Asset type (default: stock)",
    )
    pos_create.add_argument("--currency", default="TWD", help="Currency code (default: TWD)")
    pos_create.add_argument("--notes", help="Free-form notes")
    pos_create.set_defaults(func=cmd_position_create)

    pos_price = pos_sub.add_parser("update-price", help="Update a position's current price")
    pos_price.add_argument("id", help="Position ID")
    pos_price.add_argument("--price", type=float, required=True, help="New market price")
    pos_price.set_defaults(func=cmd_position_update_price)

    # -- trades --
    trd_parser = sub.add_parser("trades", aliases=["trd"], help="Trade management")
    trd_sub = trd_parser.add_subparsers(dest="action", required=True)

    trd_list = trd_sub.add_parser("list", help="List trades")
    trd_list.add_argument("--position", "-p", help="Filter by position ID")
    trd_list.set_defaults(func=cmd_trade_list)

    trd_create = trd_sub.add_parser("create", help="Record a trade")
    trd_create.add_argument("--position", "-p", required=True, help="Position ID")
    trd_create.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["buy", "sell", "dividend", "split"],
        help="Trade type",
    )
    trd_create.add_argument("--shares", type=float, required=True, help="Number of shares")
    trd_create.add_argument("--price", type=float, required=True, help="Price per share")
    trd_create.add_argument("--fee", type=float, help="Brokerage fee")
    trd_create.add_argument("--tax", type=float, help="Transaction tax")
    trd_create.add_argument("--currency", default="TWD", help="Currency code (default: TWD)")
    trd_create.add_argument(
        "--traded-at", dest="traded_at", default=None, help="Trade datetime ISO-8601 (default: now)"
    )
    trd_create.add_argument("--notes", help="Free-form notes")
    trd_create.set_defaults(func=cmd_trade_create)

    # -- portfolio --
    port_parser = sub.add_parser("portfolio", aliases=["port"], help="Portfolio summary")
    port_sub = port_parser.add_subparsers(dest="action", required=True)

    port_summary = port_sub.add_parser("summary", help="Show total portfolio gain/loss")
    port_summary.set_defaults(func=cmd_portfolio)

    # -- quotes --
    q_parser = sub.add_parser("quotes", aliases=["q"], help="Quote management")
    q_sub = q_parser.add_subparsers(dest="action", required=True)

    q_refresh = q_sub.add_parser("refresh", help="Refresh market quotes")
    q_refresh.add_argument("--symbols", help="Comma-separated ticker symbols (default: all active)")
    q_refresh.set_defaults(func=cmd_quotes_refresh)

    args = parser.parse_args()

    # Propagate top-level --json flag to sub-parsers that don't have it explicitly
    if not hasattr(args, "json"):
        args.json = False

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
