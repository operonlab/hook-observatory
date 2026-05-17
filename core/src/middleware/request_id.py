"""RequestInfoLoggingMiddleware — request_id propagation + structured HTTP logs."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from sdk_client.logging_context import request_id_var, set_request_id

logger = logging.getLogger("http.request")


class RequestInfoLoggingMiddleware(BaseHTTPMiddleware):
    """生成 request_id（優先 X-Request-ID header）→ ContextVar.set →
    log request_start + request_end → response 加 X-Request-ID header。
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Acquire or generate request_id (12-hex chars)
        rid = request.headers.get("x-request-id", "").strip()
        if not rid or not _is_valid_rid(rid):
            rid = uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)

        start = time.monotonic()
        method = request.method
        path = request.url.path

        # 2. Log request_start
        logger.info(
            "request_start",
            extra={"method": method, "path": path},
        )

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "request_failed",
                extra={"method": method, "path": path, "duration_ms": round(elapsed_ms, 2)},
            )
            request_id_var.reset(token)
            raise

        # 3. Log request_end
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request_end",
            extra={
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )

        # 4. Inject response header
        response.headers["X-Request-ID"] = rid

        request_id_var.reset(token)
        return response


def _is_valid_rid(rid: str) -> bool:
    """Accept 12-hex (our format) or arbitrary 8-64 char alnum/-_ (external trust)."""
    if not 8 <= len(rid) <= 64:
        return False
    return all(c.isalnum() or c in "-_" for c in rid)
