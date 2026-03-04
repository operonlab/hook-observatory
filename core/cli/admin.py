#!/Users/joneshong/.local/bin/python3
"""admin -- Workshop Admin CLI for health checks and audit logs.

Usage:
    admin status
    admin audit list [--module M] [--entity-type T] [--user-id U] [--action A] [--limit N]
    admin audit history <module> <entity_type> <entity_id>

Symlink: ln -sf ~/workshop/core/cli/admin.py ~/.local/bin/admin
"""

import argparse
import json
import sys

from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.admin import AdminClient


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


# ======================== Commands ========================


def cmd_status(args):
    client = AdminClient()
    try:
        result = client.status()
        if args.json:
            _json_out(result, True)
        else:
            print(f"Status: {result.get('status', result)}")
            if result.get("version"):
                print(f"Version: {result['version']}")
            if result.get("uptime"):
                print(f"Uptime: {result['uptime']}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_audit_list(args):
    client = AdminClient()
    try:
        result = client.list_audit_logs(
            module=args.module,
            entity_type=args.entity_type,
            user_id=args.user_id,
            action=args.action,
            page=1,
            page_size=args.limit,
        )
        if args.json:
            _json_out(result, True)
        else:
            items = result.get("items", result if isinstance(result, list) else [])
            total = result.get("total", len(items))
            if not items:
                print("No audit logs found.")
                return

            print(f"Audit Logs ({total} total)")
            print(f"{'Timestamp':<22} {'Module':<14} {'Entity':<14} {'Action':<14} {'User':<20}")
            print("-" * 84)
            for log in items:
                ts = str(log.get("created_at", log.get("timestamp", "?")))[:21]
                mod = log.get("module", "?")
                ent = log.get("entity_type", "?")
                act = log.get("action", "?")
                uid = log.get("user_id", "?")
                if isinstance(uid, str) and len(uid) > 19:
                    uid = uid[:8] + "..."
                print(f"{ts:<22} {mod:<14} {ent:<14} {act:<14} {uid:<20}")
    except (APIError, APIConnectionError) as e:
        _err(e)


def cmd_audit_history(args):
    client = AdminClient()
    try:
        result = client.get_entity_history(args.module, args.entity_type, args.entity_id)
        if args.json:
            _json_out(result, True)
        else:
            items = result if isinstance(result, list) else result.get("items", [])
            if not items:
                print(f"No history for {args.module}/{args.entity_type}/{args.entity_id}")
                return

            print(f"History: {args.module}/{args.entity_type}/{args.entity_id}")
            print(f"{'Timestamp':<22} {'Action':<14} {'User':<20}")
            print("-" * 56)
            for log in items:
                ts = str(log.get("created_at", log.get("timestamp", "?")))[:21]
                act = log.get("action", "?")
                uid = log.get("user_id", "?")
                if isinstance(uid, str) and len(uid) > 19:
                    uid = uid[:8] + "..."
                print(f"{ts:<22} {act:<14} {uid:<20}")
    except (APIError, APIConnectionError) as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="admin",
        description="Workshop Admin CLI for health checks and audit logs",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # status
    p_status = sub.add_parser("status", help="Health check")
    p_status.set_defaults(func=cmd_status)

    # audit
    p_audit = sub.add_parser("audit", help="Audit log management")
    sub_audit = p_audit.add_subparsers(dest="action", required=True)

    # audit list
    p_list = sub_audit.add_parser("list", help="List audit logs")
    p_list.add_argument("--module", "-m", help="Filter by module")
    p_list.add_argument("--entity-type", "-t", help="Filter by entity type")
    p_list.add_argument("--user-id", "-u", help="Filter by user ID")
    p_list.add_argument("--action", "-a", help="Filter by action")
    p_list.add_argument("--limit", "-n", type=int, default=20, help="Max results (default 20)")
    p_list.set_defaults(func=cmd_audit_list)

    # audit history
    p_hist = sub_audit.add_parser("history", help="Get entity audit history")
    p_hist.add_argument("module", help="Module name")
    p_hist.add_argument("entity_type", help="Entity type")
    p_hist.add_argument("entity_id", help="Entity ID")
    p_hist.set_defaults(func=cmd_audit_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
