#!/Users/joneshong/.local/bin/python3
"""auth -- Workshop Auth CLI for registration, login, and session management.

Usage:
    auth register <email> <password> [--name NAME]
    auth login <email> <password>
    auth logout
    auth session
    auth status  # alias for session

Symlink: ln -sf ~/workshop/core/cli/auth.py ~/.local/bin/auth
"""

import argparse
import sys

from cli.cli_helpers import err, json_out
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.auth import AuthClient


# ======================== Commands ========================


def cmd_register(args):
    client = AuthClient()
    try:
        name = args.name or args.email.split("@")[0]
        result = client.register(args.email, args.password, name)
        if args.json:
            json_out(result, True)
        else:
            print(f"User registered: {result.get('email', result.get('id', result))}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_login(args):
    client = AuthClient()
    try:
        result = client.login(args.email, args.password)
        if args.json:
            json_out(result, True)
        else:
            user = result.get("user", result)
            if isinstance(user, dict):
                print(f"Logged in as: {user.get('email', user.get('name', '?'))}")
                if user.get("role"):
                    print(f"  Role: {user['role']}")
            else:
                print(f"Logged in: {result}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_logout(args):
    client = AuthClient()
    try:
        client.logout()
        if not args.json:
            print("Logged out successfully.")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_session(args):
    client = AuthClient()
    try:
        result = client.get_session()
        if args.json:
            json_out(result, True)
        else:
            user = result.get("user", result)
            if isinstance(user, dict):
                print("Session active")
                print(f"  User:  {user.get('email', user.get('name', '?'))}")
                print(f"  ID:    {user.get('id', '?')}")
                if user.get("role"):
                    print(f"  Role:  {user['role']}")
                if result.get("space_id"):
                    print(f"  Space: {result['space_id']}")
            else:
                print(f"Session: {result}")
    except APIError as e:
        if e.status_code == 401:
            print("No active session.")
            sys.exit(1)
        err(e)
    except APIConnectionError as e:
        err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="auth",
        description="Workshop Auth CLI for registration, login, and session management",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # register
    p_reg = sub.add_parser("register", help="Register a new user")
    p_reg.add_argument("email", help="Email address")
    p_reg.add_argument("password", help="Password")
    p_reg.add_argument("--name", help="Display name (default: email prefix)")
    p_reg.set_defaults(func=cmd_register)

    # login
    p_login = sub.add_parser("login", help="Login with email/password")
    p_login.add_argument("email", help="Email address")
    p_login.add_argument("password", help="Password")
    p_login.set_defaults(func=cmd_login)

    # logout
    p_logout = sub.add_parser("logout", help="Logout (clear session)")
    p_logout.set_defaults(func=cmd_logout)

    # session
    p_session = sub.add_parser("session", help="Get current session info")
    p_session.set_defaults(func=cmd_session)

    # status (alias for session)
    p_status = sub.add_parser("status", help="Get current session info (alias for session)")
    p_status.set_defaults(func=cmd_session)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
