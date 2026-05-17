"""Shared helpers for Workshop MCP servers (FastMCP era).

Usage:
    from sdk_client.mcp_helpers import mcp_error_handler, build_body, json_text, fmt_amount

    @mcp.tool()
    @mcp_error_handler("Finance")
    async def finance_add_transaction(amount: float, ...) -> str:
        body = build_body({"amount": amount}, description=description)
        result = await to_thread(client.create_transaction, body)
        return f"Transaction created. ID: {result['id']}"
"""

import functools
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sdk_client.logging_context import JsonFormatterWithContext

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def json_text(data, **kwargs) -> str:
    """Serialize data to pretty JSON string."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str, **kwargs)


# ---------------------------------------------------------------------------
# MCP file logger
# ---------------------------------------------------------------------------

def _ensure_mcp_logger(service_name: str) -> logging.Logger | None:
    """Return a file-backed logger for the given MCP service, or None if name is empty.

    Logs are written to /opt/homebrew/var/log/workshop/mcp-{service_name}/.
    logger.propagate = False ensures stdio is never polluted (critical for MCP stdio transport).
    """
    if not service_name:
        return None

    slug = service_name.lower().replace("_", "-")
    log_dir = Path(f"/opt/homebrew/var/log/workshop/mcp-{slug}")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"mcp.{service_name}")
    if logger.handlers:
        return logger

    handler = RotatingFileHandler(
        log_dir / "mcp.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    handler.setFormatter(JsonFormatterWithContext(service=f"mcp-{slug}"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # CRITICAL: never write to stdout/stderr (MCP stdio safety)

    return logger


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def _format_error(e: Exception, service_name: str) -> str:
    """Route exception to appropriate format string.

    Handles APIError, APIConnectionError, module-specific errors,
    and generic exceptions via duck-typing (no hard imports).
    """
    # Log to file — side-effect only, does not affect return value
    logger = _ensure_mcp_logger(service_name)
    if logger:
        logger.exception(
            f"Tool error: {type(e).__name__}",
            extra={"error_type": type(e).__name__},
        )

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
