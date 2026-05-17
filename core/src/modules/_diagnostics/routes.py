import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from sdk_client.logging_context import JsonFormatterWithContext

router = APIRouter(prefix="/_diagnostics", tags=["diagnostics"])

# Dedicated logger → client-errors.log (separate from general.log to avoid noise)
_LOG_DIR = Path("/opt/homebrew/var/log/workshop/core")
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_client_logger = logging.getLogger("core.client_errors")
if not any(
    isinstance(h, RotatingFileHandler)
    and getattr(h, "baseFilename", "").endswith("client-errors.log")
    for h in _client_logger.handlers
):
    _h = RotatingFileHandler(
        _LOG_DIR / "client-errors.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    _h.setFormatter(JsonFormatterWithContext(service="core"))
    _client_logger.addHandler(_h)
    _client_logger.setLevel(logging.WARNING)
    _client_logger.propagate = False


class ClientError(BaseModel):
    message: str
    stack: str | None = None
    url: str
    user_agent: str
    request_id: str | None = None
    context: dict | None = None


class ClientErrorBatch(BaseModel):
    errors: list[ClientError]


@router.post("/client-error")
async def report_client_error(batch: ClientErrorBatch, request: Request):
    for err in batch.errors:
        _client_logger.warning(
            "frontend_error",
            extra={
                "client_message": err.message,
                "client_stack": err.stack,
                "client_url": err.url,
                "user_agent": err.user_agent,
                "client_request_id": err.request_id,
                "client_context": err.context,
                "client_ip": request.client.host if request.client else None,
            },
        )
    return {"received": len(batch.errors)}
