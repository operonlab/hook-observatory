#!/Users/joneshong/.local/bin/python3
"""Finance CLI — command-line interface for Finance Core API.

Uses the shared workshop SDK client (FinanceClient).

Usage:
    finance transactions list [--wallet W] [--category C] [--limit N]
    finance transactions create <wallet> <title> <amount> [--category C]
    finance transactions get <id>
    finance transactions delete <id>
    finance wallets list | create | sync
    finance budgets list | create | status
    finance subscriptions list [--active-only]
    finance installments list [--status S]
    finance analytics monthly [--year-month YYYY-MM]
    finance analytics trends [--months N]
    finance categories list | create
    finance transfer <from> <to> <amount>

Symlink: ln -sf ~/workshop/stations/finance-cli/finance.py ~/.local/bin/finance
"""

import argparse
import json
import sys
from datetime import datetime

from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.finance import FinanceClient

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _json_out(data, args):
    """Print JSON if --json flag is set. Returns True if printed."""
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return True
    return False


def fmt_amount(amount, currency="TWD"):
    return f"{currency} {float(amount):,.0f}"


def fmt_date(iso):
    if not iso:
        return "n/a"
    return str(iso)[:10]


def _err(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _client():
    return FinanceClient()


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------


def cmd_txn_list(args):
    client = _client()
    try:
        result = client.list_transactions(
            wallet_id=args.wallet,
            category_id=args.category,
            year_month=args.month,
            type=args.type,
            tag=args.tag,
            search=args.search,
            page=args.page,
            page_size=args.limit,
        )
        if _json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Transactions ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            icon = {"income": "+", "expense": "-", "transfer": "~"}.get(t.get("type", ""), "?")
            desc = t.get("description") or t.get("merchant") or "-"
            date = fmt_date(t.get("transacted_at"))
            print(
                f"  {icon} {fmt_amount(t['amount']):>14s}  {desc:<30s}  [{date}]  id={t['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_txn_get(args):
    client = _client()
    try:
        t = client.get_transaction(args.id)
        if _json_out(t, args):
            return
        print(f"Transaction: {t['id']}")
        print(f"  Type:     {t.get('type')}")
        print(f"  Amount:   {fmt_amount(t.get('amount', 0))}")
        print(f"  Merchant: {t.get('merchant', '-')}")
        print(f"  Desc:     {t.get('description', '-')}")
        print(f"  Wallet:   {t.get('wallet_id', '-')}")
        print(f"  Category: {t.get('category_id', '-')}")
        print(f"  Date:     {fmt_date(t.get('transacted_at'))}")
        print(f"  Payment:  {t.get('payment_method', '-')} / {t.get('payment_detail', '-')}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_txn_create(args):
    client = _client()
    try:
        data = {
            "type": args.type or "expense",
            "amount": args.amount,
            "wallet_id": args.wallet,
            "description": args.title,
        }
        if args.category:
            data["category_id"] = args.category
        if args.merchant:
            data["merchant"] = args.merchant
        if args.payment:
            data["payment_method"] = args.payment
        if args.tags:
            data["tags"] = [t.strip() for t in args.tags.split(",")]
        result = client.create_transaction(data)
        if _json_out(result, args):
            return
        print(f"Transaction created: {result['id']}")
        print(f"  {result.get('type')} | {fmt_amount(result.get('amount', 0))}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_txn_delete(args):
    client = _client()
    try:
        client.delete_transaction(args.id)
        print(f"Transaction {args.id} deleted.")
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# wallets
# ---------------------------------------------------------------------------


def cmd_wallet_list(args):
    client = _client()
    try:
        result = client.list_wallets(include_inactive=args.include_inactive)
        if _json_out(result, args):
            return
        items = result.get("items", [])
        print(f"Wallets ({len(items)} total)\n")
        total_net = 0
        for w in items:
            balance = float(w.get("current_balance", 0))
            total_net += balance
            credit = f" (limit: {fmt_amount(w['credit_limit'])})" if w.get("credit_limit") else ""
            print(
                f"  {w.get('icon', '')} {w['name']:<20s}  {fmt_amount(balance):>14s}  [{w['type']}]{credit}  id={w['id'][:8]}"
            )
        print(f"\n  Net worth: {fmt_amount(total_net)}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_wallet_create(args):
    client = _client()
    try:
        data = {"name": args.name, "type": args.type}
        if args.currency:
            data["currency"] = args.currency
        if args.balance is not None:
            data["initial_balance"] = args.balance
        result = client.create_wallet(data)
        if _json_out(result, args):
            return
        print(f"Wallet created: {result['id']}")
        print(
            f"  {result['name']} | {result['type']} | {fmt_amount(result.get('current_balance', 0))}"
        )
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_wallet_sync(args):
    client = _client()
    try:
        data = {"synced_balance": args.balance}
        if args.notes:
            data["notes"] = args.notes
        result = client.sync_wallet(args.wallet_id, data)
        if _json_out(result, args):
            return
        diff = float(result.get("difference", 0))
        diff_str = f"{diff:+,.0f}" if diff != 0 else "0 (matched)"
        print("Wallet synced.")
        print(f"  Synced balance:     {fmt_amount(result.get('synced_balance', 0))}")
        print(f"  Calculated balance: {fmt_amount(result.get('calculated_balance', 0))}")
        print(f"  Difference:         {diff_str}")
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# budgets
# ---------------------------------------------------------------------------


def cmd_budget_list(args):
    client = _client()
    try:
        result = client.list_budgets(year_month=args.month)
        if _json_out(result, args):
            return
        items = result.get("items", [])
        print(f"Budgets ({len(items)} total)\n")
        for b in items:
            print(
                f"  {b.get('year_month', '?')}  budget: {fmt_amount(b.get('budget_amount', 0))}  id={b['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_budget_create(args):
    client = _client()
    try:
        data = {"year_month": args.month, "budget_amount": args.amount}
        if args.savings:
            data["savings_target"] = args.savings
        result = client.upsert_budget(data)
        if _json_out(result, args):
            return
        print(f"Budget set for {args.month}: {fmt_amount(args.amount)}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_budget_status(args):
    client = _client()
    try:
        month = args.month or datetime.now().strftime("%Y-%m")
        result = client.get_budget_status(month)
        if _json_out(result, args):
            return
        budget = float(result.get("budget_amount", 0))
        spent = float(result.get("total_spent", 0))
        print(f"Budget Status -- {month}\n")
        print(f"  Budget:    {fmt_amount(budget)}")
        print(f"  Spent:     {fmt_amount(spent)}")
        print(f"  Remaining: {fmt_amount(budget - spent)}")
        if budget > 0 and spent > budget:
            print(f"\n  WARNING: Over budget by {fmt_amount(spent - budget)}")
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------


def cmd_sub_list(args):
    client = _client()
    try:
        status = "active" if args.active_only else args.status
        result = client.list_subscriptions(status=status)
        if _json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Subscriptions ({total} total)\n")
        for s in items:
            icon = {"active": "*", "paused": "||", "cancelled": "x"}.get(s.get("status", ""), "?")
            print(
                f"  [{icon}] {s['name']:<25s}  {fmt_amount(s['amount']):>12s} / {s.get('billing_cycle', '?')}"
                f"  next: {fmt_date(s.get('next_billing'))}  id={s['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_sub_create(args):
    client = _client()
    try:
        data = {
            "name": args.name,
            "amount": args.amount,
            "billing_cycle": args.cycle,
            "start_date": args.start_date,
        }
        if args.wallet:
            data["wallet_id"] = args.wallet
        if args.category:
            data["category_id"] = args.category
        result = client.create_subscription(data)
        if _json_out(result, args):
            return
        print(f"Subscription created: {result['id']}")
        print(
            f"  {result['name']} | {fmt_amount(result['amount'])} / {result.get('billing_cycle')}"
        )
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# installments
# ---------------------------------------------------------------------------


def cmd_inst_list(args):
    client = _client()
    try:
        result = client.list_installments(status=args.status)
        if _json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Installment Plans ({total} total)\n")
        for p in items:
            icon = {"active": "*", "completed": "v", "cancelled": "x"}.get(p.get("status", ""), "?")
            paid = p.get("paid_count", 0)
            total_n = p.get("num_installments", 0)
            print(
                f"  [{icon}] {p['description']:<30s}  {fmt_amount(p['total_amount']):>14s}"
                f"  {paid}/{total_n}  per: {fmt_amount(p.get('installment_amount', 0))}  id={p['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_inst_create(args):
    client = _client()
    try:
        data = {
            "description": args.description,
            "total_amount": args.amount,
            "num_installments": args.periods,
            "wallet_id": args.wallet,
            "payment_method": args.payment,
            "start_date": args.start_date,
        }
        if args.category:
            data["category_id"] = args.category
        result = client.create_installment(data)
        if _json_out(result, args):
            return
        print(f"Installment plan created: {result['id']}")
        print(
            f"  {result['description']} | {fmt_amount(result['total_amount'])} / {result['num_installments']} periods"
        )
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# analytics
# ---------------------------------------------------------------------------


def cmd_analytics_monthly(args):
    client = _client()
    try:
        month = args.month or datetime.now().strftime("%Y-%m")
        result = client.monthly_summary(month)
        if _json_out(result, args):
            return
        income = float(result.get("total_income", 0))
        expense = float(result.get("total_expense", 0))
        print(f"Monthly Summary -- {month}\n")
        print(f"  Income:  {fmt_amount(income)}")
        print(f"  Expense: {fmt_amount(expense)}")
        print(f"  Net:     {fmt_amount(income - expense)}")
        categories = result.get("categories", [])
        if categories:
            print("\n  By Category:")
            for c in categories:
                print(f"    {c.get('icon', '')} {c['name']}: {fmt_amount(c['amount'])}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_analytics_trends(args):
    client = _client()
    try:
        result = client.monthly_trends(months=args.months)
        if _json_out(result, args):
            return
        trends = result if isinstance(result, list) else result.get("trends", [])
        print(f"Spending Trends (past {args.months} months)\n")
        for t in trends:
            income = float(t.get("income", 0))
            expense = float(t.get("expense", 0))
            bar_len = min(30, int(expense / 1000))
            bar = "#" * bar_len
            print(
                f"  {t['month']}  income: {fmt_amount(income):>12s}  expense: {fmt_amount(expense):>12s}  {bar}"
            )
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# categories
# ---------------------------------------------------------------------------


def cmd_cat_list(args):
    client = _client()
    try:
        result = client.list_categories(flat=args.flat)
        if _json_out(result, args):
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"Categories ({len(items)} total)\n")
        for c in items:
            indent = "  " if c.get("parent_id") else ""
            print(f"  {indent}{c.get('icon', '')} {c['name']}  id={c['id'][:8]}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_cat_create(args):
    client = _client()
    try:
        data = {"name": args.name}
        if args.icon:
            data["icon"] = args.icon
        if args.parent:
            data["parent_id"] = args.parent
        result = client.create_category(data)
        if _json_out(result, args):
            return
        print(
            f"Category created: {result.get('icon', '')} {result['name']} (id={result['id'][:8]})"
        )
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# transfer
# ---------------------------------------------------------------------------


def cmd_transfer(args):
    client = _client()
    try:
        data = {
            "from_wallet_id": args.from_wallet,
            "to_wallet_id": args.to_wallet,
            "amount": args.amount,
        }
        if args.description:
            data["description"] = args.description
        if args.fee:
            data["fee"] = args.fee
        result = client.transfer(data)
        if _json_out(result, args):
            return
        print("Transfer completed.")
        print(
            f"  From: {args.from_wallet[:8]}  To: {args.to_wallet[:8]}  Amount: {fmt_amount(args.amount)}"
        )
    except (APIError, APIConnectionError) as e:
        _err(e)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="finance", description="Finance CLI for Workshop Core API"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- transactions --
    txn_parser = sub.add_parser("transactions", aliases=["txn"], help="Transaction management")
    txn_sub = txn_parser.add_subparsers(dest="action", required=True)

    txn_list = txn_sub.add_parser("list", help="List transactions")
    txn_list.add_argument("--wallet", "-w", help="Filter by wallet ID")
    txn_list.add_argument("--category", "-c", help="Filter by category ID")
    txn_list.add_argument("--month", "-m", help="Filter by YYYY-MM")
    txn_list.add_argument("--type", "-t", choices=["income", "expense", "transfer"])
    txn_list.add_argument("--tag", help="Filter by tag")
    txn_list.add_argument("--search", "-s", help="Full-text search")
    txn_list.add_argument("--limit", type=int, default=20, help="Page size")
    txn_list.add_argument("--page", type=int, default=1)
    txn_list.set_defaults(func=cmd_txn_list)

    txn_get = txn_sub.add_parser("get", help="Get transaction by ID")
    txn_get.add_argument("id", help="Transaction ID")
    txn_get.set_defaults(func=cmd_txn_get)

    txn_create = txn_sub.add_parser("create", help="Create a transaction")
    txn_create.add_argument("wallet", help="Wallet ID")
    txn_create.add_argument("title", help="Description")
    txn_create.add_argument("amount", type=float, help="Amount")
    txn_create.add_argument(
        "--type", "-t", default="expense", choices=["income", "expense", "transfer"]
    )
    txn_create.add_argument("--category", "-c", help="Category ID")
    txn_create.add_argument("--merchant", help="Merchant name")
    txn_create.add_argument("--payment", help="Payment method")
    txn_create.add_argument("--tags", help="Comma-separated tags")
    txn_create.set_defaults(func=cmd_txn_create)

    txn_del = txn_sub.add_parser("delete", help="Delete a transaction")
    txn_del.add_argument("id", help="Transaction ID")
    txn_del.set_defaults(func=cmd_txn_delete)

    # -- wallets --
    w_parser = sub.add_parser("wallets", aliases=["w"], help="Wallet management")
    w_sub = w_parser.add_subparsers(dest="action", required=True)

    w_list = w_sub.add_parser("list", help="List wallets")
    w_list.add_argument("--include-inactive", action="store_true")
    w_list.set_defaults(func=cmd_wallet_list)

    w_create = w_sub.add_parser("create", help="Create a wallet")
    w_create.add_argument("name", help="Wallet name")
    w_create.add_argument(
        "type", choices=["bank_account", "credit_card", "cash", "e_wallet", "investment"]
    )
    w_create.add_argument("--currency", default="TWD")
    w_create.add_argument("--balance", type=float, help="Initial balance")
    w_create.set_defaults(func=cmd_wallet_create)

    w_sync = w_sub.add_parser("sync", help="Sync wallet balance")
    w_sync.add_argument("wallet_id", help="Wallet ID")
    w_sync.add_argument("balance", type=float, help="Actual balance")
    w_sync.add_argument("--notes", help="Sync notes")
    w_sync.set_defaults(func=cmd_wallet_sync)

    # -- budgets --
    b_parser = sub.add_parser("budgets", aliases=["b"], help="Budget management")
    b_sub = b_parser.add_subparsers(dest="action", required=True)

    b_list = b_sub.add_parser("list", help="List budgets")
    b_list.add_argument("--month", "-m", help="Filter by YYYY-MM")
    b_list.set_defaults(func=cmd_budget_list)

    b_create = b_sub.add_parser("create", help="Set a budget")
    b_create.add_argument("month", help="YYYY-MM")
    b_create.add_argument("amount", type=float, help="Budget amount")
    b_create.add_argument("--savings", type=float, help="Savings target")
    b_create.set_defaults(func=cmd_budget_create)

    b_status = b_sub.add_parser("status", help="Budget consumption status")
    b_status.add_argument("--month", "-m", help="YYYY-MM (default: current)")
    b_status.set_defaults(func=cmd_budget_status)

    # -- subscriptions --
    s_parser = sub.add_parser("subscriptions", aliases=["sub"], help="Subscription management")
    s_sub = s_parser.add_subparsers(dest="action", required=True)

    s_list = s_sub.add_parser("list", help="List subscriptions")
    s_list.add_argument("--active-only", action="store_true")
    s_list.add_argument("--status", choices=["active", "paused", "cancelled"])
    s_list.set_defaults(func=cmd_sub_list)

    s_create = s_sub.add_parser("create", help="Create a subscription")
    s_create.add_argument("name", help="Subscription name")
    s_create.add_argument("amount", type=float, help="Amount")
    s_create.add_argument("cycle", choices=["monthly", "yearly", "weekly"])
    s_create.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    s_create.add_argument("--wallet", help="Wallet ID")
    s_create.add_argument("--category", help="Category ID")
    s_create.set_defaults(func=cmd_sub_create)

    # -- installments --
    i_parser = sub.add_parser("installments", aliases=["inst"], help="Installment management")
    i_sub = i_parser.add_subparsers(dest="action", required=True)

    i_list = i_sub.add_parser("list", help="List installment plans")
    i_list.add_argument("--status", choices=["active", "completed", "cancelled"])
    i_list.set_defaults(func=cmd_inst_list)

    i_create = i_sub.add_parser("create", help="Create an installment plan")
    i_create.add_argument("description", help="Description")
    i_create.add_argument("amount", type=float, help="Total amount")
    i_create.add_argument("periods", type=int, help="Number of installments")
    i_create.add_argument("wallet", help="Wallet ID")
    i_create.add_argument("payment", help="Payment method")
    i_create.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    i_create.add_argument("--category", help="Category ID")
    i_create.set_defaults(func=cmd_inst_create)

    # -- analytics --
    a_parser = sub.add_parser("analytics", aliases=["a"], help="Financial analytics")
    a_sub = a_parser.add_subparsers(dest="action", required=True)

    a_monthly = a_sub.add_parser("monthly", help="Monthly summary")
    a_monthly.add_argument("--month", "-m", help="YYYY-MM (default: current)")
    a_monthly.set_defaults(func=cmd_analytics_monthly)

    a_trends = a_sub.add_parser("trends", aliases=["spending"], help="Multi-month spending trends")
    a_trends.add_argument("--months", "-n", type=int, default=6, help="Number of months")
    a_trends.set_defaults(func=cmd_analytics_trends)

    # -- categories --
    c_parser = sub.add_parser("categories", aliases=["cat"], help="Category management")
    c_sub = c_parser.add_subparsers(dest="action", required=True)

    c_list = c_sub.add_parser("list", help="List categories")
    c_list.add_argument("--flat", action="store_true", help="Flat list instead of tree")
    c_list.set_defaults(func=cmd_cat_list)

    c_create = c_sub.add_parser("create", help="Create a category")
    c_create.add_argument("name", help="Category name")
    c_create.add_argument("--icon", help="Emoji icon")
    c_create.add_argument("--parent", help="Parent category ID")
    c_create.set_defaults(func=cmd_cat_create)

    # -- transfer --
    t_parser = sub.add_parser("transfer", help="Wallet-to-wallet transfer")
    t_parser.add_argument("from_wallet", help="Source wallet ID")
    t_parser.add_argument("to_wallet", help="Target wallet ID")
    t_parser.add_argument("amount", type=float, help="Transfer amount")
    t_parser.add_argument("--description", "-d", help="Transfer description")
    t_parser.add_argument("--fee", type=float, help="Transfer fee")
    t_parser.set_defaults(func=cmd_transfer)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
