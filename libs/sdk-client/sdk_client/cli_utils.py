"""Shared CLI utilities for Workshop stations and tools."""

from __future__ import annotations

import json
import sys
from typing import Any


def json_out(data: Any, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=str))


def error_exit(msg: str, *, code: int = 1) -> None:
    """Print error message to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def table_print(
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
    *,
    max_width: int = 40,
) -> None:
    """Print a list of dicts as an aligned text table.

    If *columns* is None, keys are inferred from the first row.
    """
    if not rows:
        return
    cols = columns or list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    str_rows: list[dict[str, str]] = []
    for row in rows:
        sr = {}
        for c in cols:
            val = str(row.get(c, ""))
            if len(val) > max_width:
                val = val[: max_width - 1] + "\u2026"
            sr[c] = val
            widths[c] = max(widths[c], len(val))
        str_rows.append(sr)
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for sr in str_rows:
        print("  ".join(sr.get(c, "").ljust(widths[c]) for c in cols))
