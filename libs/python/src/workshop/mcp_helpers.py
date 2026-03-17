"""Shared helpers for Workshop MCP servers (FastMCP era).

Usage:
    from workshop.mcp_helpers import mcp_error_handler, build_body, json_text, fmt_amount

    @mcp.tool()
    @mcp_error_handler("Finance")
    async def finance_add_transaction(amount: float, ...) -> str:
        body = build_body({"amount": amount}, description=description)
        result = await to_thread(client.create_transaction, body)
        return f"Transaction created. ID: {result['id']}"
"""

import functools
import json

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def json_text(data, **kwargs) -> str:
    """Serialize data to pretty JSON string."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str, **kwargs)


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def _format_error(e: Exception, service_name: str) -> str:
    """Route exception to appropriate format string.

    Handles APIError, APIConnectionError, module-specific errors,
    and generic exceptions via duck-typing (no hard imports).
    """
    prefix = f"{service_name} error" if service_name else "Error"

    # APIError-like (has status_code + detail)
    if hasattr(e, "status_code") and hasattr(e, "detail"):
        return f"{prefix} ({e.status_code}): {e.detail}"

    # APIConnectionError-like or module-specific error (has message)
    if hasattr(e, "message"):
        return f"{prefix}: {e.message}"

    # httpx / requests errors
    if hasattr(e, "response") and hasattr(e, "request"):
        return f"{prefix}: HTTP {getattr(e.response, 'status_code', '?')}: {e}"

    # Generic
    return f"Error: {type(e).__name__}: {e}"


def mcp_error_handler(service_name: str = ""):
    """Decorator — catches all errors and returns a formatted string.

    Usage:
        @mcp.tool()
        @mcp_error_handler("Finance")
        async def my_tool(...) -> str:
            ...  # no try/except needed
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                return _format_error(e, service_name)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Request body builder
# ---------------------------------------------------------------------------

def build_body(required: dict | None = None, **optional) -> dict:
    """Build request body from required fields + optional kwargs.

    Skips None, empty string, and empty list values from optional kwargs.

    Usage:
        body = build_body(
            {"type": "expense", "amount": 100},
            description=description,  # included if truthy
            tags=tags,                # skipped if None or []
        )
    """
    body = dict(required) if required else {}
    for k, v in optional.items():
        if v is not None and v != "" and v != []:
            body[k] = v
    return body


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_amount(v, currency: str = "TWD", decimals: int = 0) -> str:
    """Format a monetary amount with currency prefix.

    Examples:
        fmt_amount(1234.5)           → "TWD 1,235"
        fmt_amount(1234.5, decimals=2) → "TWD 1,234.50"
    """
    return f"{currency} {float(v):,.{decimals}f}"
