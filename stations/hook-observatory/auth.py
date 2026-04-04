"""Workshop cookie auth middleware — validates workshop_session cookie.

Set `auth_enabled: true` in config.yaml to require authentication.
Default: disabled (open access on localhost).
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import config

_serializer = URLSafeTimedSerializer(config.secret_key)

_ANON_USER = {"status": "active", "source": "auth-disabled"}


async def require_auth(request: Request) -> dict:
    """FastAPI dependency — validate session or pass through if auth is disabled."""
    if not config.auth_enabled:
        return _ANON_USER

    # Local key auth (CLI/SDK)
    local_key = request.headers.get("x-local-key")
    if local_key and local_key == config.secret_key:
        return {"status": "active", "source": "local-key"}

    cookie = request.cookies.get(config.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        data = _serializer.loads(cookie, max_age=config.session_max_age)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Session expired")

    # V2 Core format: cookie contains a signed session token (string).
    if isinstance(data, str):
        return {"status": "active", "source": "v2-token"}

    # V1 format: cookie contains signed dict with embedded user info.
    user = data.get("user") if isinstance(data, dict) else None
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="Invalid session")

    return user
