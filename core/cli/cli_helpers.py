"""Shared CLI output helpers — eliminates per-module _json_out / _err / fmt_* boilerplate.

Usage:
    from cli.cli_helpers import json_out, err, fmt_date, fmt_amount
"""

import json
import sys


def json_out(data, args_or_flag=None) -> bool:
    """Print JSON and return True if JSON output is requested, else return False.

    Supports two calling conventions (duck-typed):
        json_out(data, args)       — checks args.json or args.json_output
        json_out(data, True/False) — direct bool flag
    """
    if isinstance(args_or_flag, bool):
        flag = args_or_flag
    elif args_or_flag is not None:
        flag = getattr(args_or_flag, "json", False) or getattr(
            args_or_flag, "json_output", False
        )
    else:
        flag = False

    if flag:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return True
    return False


def err(exc, exit_fn=sys.exit):
    """Print error to stderr and exit with structured code."""
    print(f"Error: {exc}", file=sys.stderr)
    # Use exit_codes if available, otherwise exit 1
    try:
        from cli.exit_codes import exit_code_for

        exit_fn(exit_code_for(exc))
    except ImportError:
        exit_fn(1)


def fmt_date(iso: str | None) -> str:
    """Format ISO date string to YYYY-MM-DD. Returns 'n/a' for None."""
    if not iso:
        return "n/a"
    return str(iso)[:10]


def fmt_amount(v, currency: str = "TWD", decimals: int = 0) -> str:
    """Format monetary amount with currency prefix."""
    return f"{currency} {float(v):,.{decimals}f}"
