"""Workshop auth — nginx auth_request handles authentication.

All requests through nginx are pre-authenticated via /_v2_auth_check.
This dependency is a no-op passthrough; it exists so routes remain
annotated with Depends(require_auth) for documentation purposes.

For direct access (dev/testing without nginx), no auth is enforced.
"""

from __future__ import annotations

from fastapi import Request


async def require_auth(request: Request) -> dict:
    """No-op: nginx auth_request already validated the session."""
    return {"status": "active", "source": "nginx-passthrough"}
