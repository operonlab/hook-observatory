"""Cookie-based session middleware using itsdangerous signed cookie + Redis.

Cookie stores only the session token (signed). User data is looked up from Redis.
"""

import json

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
        # --- Decode session token from cookie ---
        session_token: str | None = None
        cookie_value = request.cookies.get(settings.session_cookie_name)

        if cookie_value:
            try:
                session_token = _serializer.loads(
                    cookie_value,
                    max_age=settings.session_max_age,
                )
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
                logging.getLogger(__name__).warning("Redis session lookup failed: %s", e)
                session_token = None  # treat as unauthenticated
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
