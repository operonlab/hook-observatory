"""Auth API client -- Core module at /api/auth.

Wraps registration, login/logout, session management, and OAuth flows.

Usage:
    from workshop.clients.auth import AuthClient

    client = AuthClient()
    session = client.login("user@example.com", "password")
    info = client.get_session()
"""

from typing import Any

from ._base import BaseClient


class AuthClient(BaseClient):
    """HTTP client for the Auth Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="auth", **kwargs)

    # ======================== Registration ========================

    def register(self, email: str, password: str, name: str) -> dict:
        """Register a new user. POST /register

        Args:
            email: User email address.
            password: User password.
            name: Display name.
        """
        return self._post(
            "/register",
            {
                "email": email,
                "password": password,
                "name": name,
            },
        )

    # ======================== Login / Logout ========================

    def login(self, email: str, password: str) -> dict:
        """Login with email and password. POST /login

        Args:
            email: User email address.
            password: User password.
        """
        return self._post(
            "/login",
            {
                "email": email,
                "password": password,
            },
        )

    def logout(self) -> None:
        """Logout (clear session). POST /logout"""
        self._post("/logout")

    # ======================== Session ========================

    def get_session(self) -> dict:
        """Get current session info. GET /session"""
        return self._get("/session")

    # ======================== OAuth ========================

    def get_oauth_url(self, provider: str, redirect: str | None = None) -> dict:
        """Start an OAuth flow and get the redirect URL. GET /oauth/{provider}

        Args:
            provider: OAuth provider ('google' or 'github').
            redirect: Optional redirect URL after OAuth completes.
        """
        params = {}
        if redirect:
            params["redirect"] = redirect
        return self._get(f"/login/{provider}", params or None)
