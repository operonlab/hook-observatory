"""Admin audit middleware — isolate admin mutations to a dedicated audit log.

POST/PUT/PATCH/DELETE under /api/admin/* are written to:
  /opt/homebrew/var/log/workshop/core/admin-audit.log

This logger's `propagate = False` ensures audit events do NOT leak into
core/general.log, keeping the audit trail clean for compliance review.

GET requests are intentionally NOT logged here — they're already in
general.log via RequestInfoLoggingMiddleware. Audit log is for mutations only.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from sdk_client.logging_context import JsonFormatterWithContext

_LOG_DIR = Path("/opt/homebrew/var/log/workshop/core")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_audit_logger = logging.getLogger("core.admin.audit")

# Idempotent setup — multiple imports won't duplicate handlers
_existing = any(
    isinstance(h, RotatingFileHandler)
    and getattr(h, "baseFilename", "").endswith("admin-audit.log")
    for h in _audit_logger.handlers
)
if not _existing:
    _handler = RotatingFileHandler(
        _LOG_DIR / "admin-audit.log", maxBytes=10 * 1024 * 1024, backupCount=10
    )
    _handler.setFormatter(JsonFormatterWithContext(service="core"))
    _audit_logger.addHandler(_handler)
    _audit_logger.setLevel(logging.INFO)
    _audit_logger.propagate = False  # Do not leak into general.log

_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ADMIN_PREFIX = "/api/admin"


class AdminAuditMiddleware(BaseHTTPMiddleware):
    """Log admin mutations to admin-audit.log only (not general.log)."""

    async def dispatch(self, request: Request, call_next):
        is_admin_mutation = (
            request.method in _AUDIT_METHODS
            and request.url.path.startswith(_ADMIN_PREFIX)
        )

        if is_admin_mutation:
            _audit_logger.info(
                "admin_mutation_start",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query) if request.url.query else None,
                },
            )

        response = await call_next(request)

        if is_admin_mutation:
            _audit_logger.info(
                "admin_mutation_end",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )

        return response
