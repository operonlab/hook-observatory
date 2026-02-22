"""Reverse proxy — forward requests to downstream services."""

import httpx
from fastapi import APIRouter, Request, Response, HTTPException, status

from gateway.config import settings

router = APIRouter(tags=["proxy"])


@router.api_route(
    "/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(service: str, path: str, request: Request):
    base_url = settings.service_registry.get(service)
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service}' not found in registry",
        )

    # Build target URL
    target_url = f"{base_url}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Forward headers (skip hop-by-hop)
    forward_headers = dict(request.headers)
    for h in ("host", "transfer-encoding", "connection"):
        forward_headers.pop(h, None)

    # Inject user context if authenticated
    user = getattr(request.state, "user", None)
    if user:
        forward_headers["x-user-id"] = user.get("id", "")
        forward_headers["x-user-role"] = user.get("role", "")
        forward_headers["x-user-status"] = user.get("status", "")

    # Read body
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body,
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Service '{service}' is unreachable",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Service '{service}' timed out",
        )

    # Build response (skip hop-by-hop headers)
    excluded = {"transfer-encoding", "connection", "content-encoding", "content-length"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )
