"""Cookie-based session middleware using itsdangerous signed serializer."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from src.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key)


class SessionMiddleware(BaseHTTPMiddleware):
    """Read/write signed session cookie on every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # --- Decode session from cookie ---
        session_data: dict = {}
        cookie_value = request.cookies.get(settings.session_cookie_name)

        if cookie_value:
            try:
                session_data = _serializer.loads(
                    cookie_value,
                    max_age=settings.session_max_age,
                )
            except (BadSignature, SignatureExpired):
                session_data = {}

        # Attach to request state
        request.state.session = session_data
        request.state.user = session_data.get("user")
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
                samesite="lax",
            )
        elif request.state._session_modified:
            signed = _serializer.dumps(request.state.session)
            response.set_cookie(
                key=settings.session_cookie_name,
                value=signed,
                max_age=settings.session_max_age,
                path="/",
                httponly=True,
                samesite="lax",
            )

        return response
