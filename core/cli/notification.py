#!/Users/joneshong/.local/bin/python3
"""notification -- Workshop Notification push subscription CLI.

Usage:
    notification vapid-key
    notification subscriptions list
    notification subscriptions create <endpoint> <p256dh> <auth>
    notification subscriptions delete <endpoint>
    notification subscriptions preferences <sub_id> [--key value ...]

Symlink: ln -sf ~/workshop/core/cli/notification.py ~/.local/bin/notification
"""

import argparse
import json
import sys

from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.notification import NotificationClient




# ======================== Commands ========================


def cmd_vapid_key(args):
    client = NotificationClient()
    try:
        result = client.get_vapid_key()
        if args.json:
            json_out(result, True)
        else:
            print(f"VAPID Public Key: {result.get('public_key', result)}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_sub_list(args):
    client = NotificationClient()
    try:
        subs = client.list_subscriptions()
        if args.json:
            json_out(subs, True)
        else:
            if not subs:
                print("No subscriptions found.")
                return
            items = subs if isinstance(subs, list) else subs.get("items", subs)
            for s in items if isinstance(items, list) else [items]:
                sid = s.get("id", "?")
                endpoint = s.get("endpoint", "?")
                print(f"  [{sid}] {endpoint[:60]}...")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_sub_create(args):
    client = NotificationClient()
    try:
        result = client.create_subscription(
            {
                "endpoint": args.endpoint,
                "p256dh": args.p256dh,
                "auth": args.auth_key,
            }
        )
        if args.json:
            json_out(result, True)
        else:
            print(f"Subscription created: {result.get('id', result)}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_sub_delete(args):
    client = NotificationClient()
    try:
        client.delete_subscription(args.endpoint)
        if not args.json:
            print("Subscription deleted.")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_sub_preferences(args):
    client = NotificationClient()
    try:
        # Parse --key value pairs from remaining args
        prefs = {}
        it = iter(args.prefs)
        for item in it:
            if item.startswith("--"):
                key = item.lstrip("-")
                val = next(it, "true")
                # Try to parse as JSON value (bool, int, etc.)
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    print(f"Warning: invalid JSON for {key}, using raw value", file=sys.stderr)
                prefs[key] = val
        if not prefs:
            print("No preferences provided. Use --key value pairs.", file=sys.stderr)
            sys.exit(1)
        result = client.update_preferences(args.sub_id, prefs)
        if args.json:
            json_out(result, True)
        else:
            print(f"Preferences updated for {args.sub_id}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="notification",
        description="Workshop Notification push subscription CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # vapid-key
    p_vapid = sub.add_parser("vapid-key", help="Get VAPID public key")
    p_vapid.set_defaults(func=cmd_vapid_key)

    # subscriptions
    p_subs = sub.add_parser("subscriptions", help="Manage push subscriptions")
    sub_subs = p_subs.add_subparsers(dest="action", required=True)

    # subscriptions list
    p_list = sub_subs.add_parser("list", help="List subscriptions")
    p_list.set_defaults(func=cmd_sub_list)

    # subscriptions create
    p_create = sub_subs.add_parser("create", help="Create a subscription")
    p_create.add_argument("endpoint", help="Push endpoint URL")
    p_create.add_argument("p256dh", help="p256dh key")
    p_create.add_argument("auth_key", metavar="auth", help="Auth key")
    p_create.set_defaults(func=cmd_sub_create)

    # subscriptions delete
    p_del = sub_subs.add_parser("delete", help="Delete a subscription")
    p_del.add_argument("endpoint", help="Push endpoint URL")
    p_del.set_defaults(func=cmd_sub_delete)

    # subscriptions preferences
    p_pref = sub_subs.add_parser("preferences", help="Update subscription preferences")
    p_pref.add_argument("sub_id", help="Subscription ID")
    p_pref.add_argument("prefs", nargs=argparse.REMAINDER, help="--key value pairs")
    p_pref.set_defaults(func=cmd_sub_preferences)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
