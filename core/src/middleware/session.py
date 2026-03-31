"""Cookie-based session middleware using itsdangerous signed cookie + Redis.

Cookie stores only the session token (signed). User data is looked up from Redis.
"""

import json
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings
from src.shared.redis import get_redis

_serializer = URLSafeTimedSerializer(settings.secret_key)


class SessionMiddleware(BaseHTTPMiddleware):
    """Read/write signed session cookie + Redis lookup on every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # --- Internal API key bypass (SDK/MCP/CLI) ---
        internal_key = request.headers.get("x-internal-key")
        if (
            internal_key
            and settings.internal_api_key
            and secrets.compare_digest(internal_key, settings.internal_api_key)
        ):
            request.state.user = {
                "id": "system",
                "email": "system@internal",
                "role": "admin",
                "status": "active",
            }
            request.state.session = {}
            request.state._session_modified = False
            request.state._session_cleared = False
            return await call_next(request)

        # --- Decode session token from cookie ---
        session_token: str | None = None
        cookie_value = request.cookies.get(settings.session_cookie_name)

        if cookie_value:
            try:
                payload = _serializer.loads(
                    cookie_value,
                    max_age=settings.session_max_age,
                )
                # New format: token is a plain str.
                # Old format: cookie stored the full session dict — discard it.
                session_token = payload if isinstance(payload, str) else None
            except (BadSignature, SignatureExpired):
                session_token = None

        # --- Look up user from Redis ---
        user_data: dict | None = None
        if session_token:
            import hashlib
            import logging

            token_hash = hashlib.sha256(session_token.encode()).hexdigest()
            redis = get_redis()
            try:
                raw = await redis.get(f"auth:session:{token_hash}")
                if raw:
                    user_data = json.loads(raw)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Redis session lookup failed — user_data=None, auth layer will 401: %s", e
                )
                # user_data remains None → get_current_user() will raise 401 on protected
                # endpoints. Only unprotected endpoints (/status) remain accessible.
            finally:
                await redis.aclose()

        # Attach to request state
        request.state.session = {"token": session_token} if session_token else {}
        request.state.user = user_data
        request.state._session_modified = False
        request.state._session_cleared = False

        # --- Process request ---
        response: Response = await call_next(request)

        # --- Write session cookie back if modified ---
        if request.state._session_cleared:
            response.delete_cookie(
                settings.session_cookie_name,
                path="/",
                httponly=True,
                secure=True,
                samesite="lax",
            )
        elif request.state._session_modified:
            token = request.state.session.get("token")
            if token:
                signed = _serializer.dumps(token)
                response.set_cookie(
                    key=settings.session_cookie_name,
                    value=signed,
                    max_age=settings.session_max_age,
                    path="/",
                    httponly=True,
                    secure=True,
                    samesite="lax",
                )

        return response
