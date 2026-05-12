"""auth_standalone.py — Drop-in auth adapter for memvault-os standalone deployment.

Replaces workshop's itsdangerous + Redis session auth with a single admin token
read from the environment variable MEMVAULT_OS_TOKEN.

Usage in downstream main.py / deps.py:

    from adapter.auth_standalone import get_current_user, User

    @app.get("/api/memvault/blocks")
    async def list_blocks(user: User = Depends(get_current_user)):
        ...

Workshop compatibility surface:
- `User` Pydantic model — same field names used by workshop auth module
- `get_current_user` FastAPI dependency — raises HTTP 401 on bad / missing token
- `require_permission(permission: str)` — no-op stub (all permissions pass for admin token)

Limitations:
- Single-user only (one admin token).
- No RBAC / Space scoping / session management.
- user.id is fixed to "standalone-admin".
- user.space_id is fixed to "default" (configure via MEMVAULT_OS_SPACE_ID if needed).
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_TOKEN_ENV_VAR = "MEMVAULT_OS_TOKEN"
_SPACE_ID_ENV_VAR = "MEMVAULT_OS_SPACE_ID"
_DEFAULT_SPACE_ID = "default"

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_expected_token() -> str:
    token = os.environ.get(_TOKEN_ENV_VAR, "").strip()
    if not token:
        raise RuntimeError(
            f"Environment variable {_TOKEN_ENV_VAR!r} is not set. "
            "Set it to a strong random token before starting memvault-os.\n"
            "  Example: export MEMVAULT_OS_TOKEN=$(openssl rand -hex 32)"
        )
    return token


# ---------------------------------------------------------------------------
# User model — compatible with workshop auth.schemas.UserResponse surface
# ---------------------------------------------------------------------------


class User(BaseModel):
    """Authenticated user representation.

    Fields match the workshop auth module's public interface so memvault
    core code doesn't need to distinguish between upstream and standalone.
    """

    id: str
    """User identifier — fixed to 'standalone-admin' in standalone mode."""

    role: str
    """Role — fixed to 'admin' in standalone mode (all permissions granted)."""

    space_id: str
    """Active space — read from MEMVAULT_OS_SPACE_ID, defaults to 'default'."""

    email: str | None = None
    """Email — unused in standalone mode, present for interface compatibility."""

    is_active: bool = True
    """Whether the user account is active — always True in standalone mode."""

    # Workshop-compat extras (safe to ignore downstream)
    permissions: list[str] = ["*"]
    """Effective permissions — '*' means all in standalone mode."""


def _build_admin_user() -> User:
    space_id = os.environ.get(_SPACE_ID_ENV_VAR, _DEFAULT_SPACE_ID).strip() or _DEFAULT_SPACE_ID
    return User(
        id="standalone-admin",
        role="admin",
        space_id=space_id,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer_scheme),
    ] = None,
) -> User:
    """FastAPI dependency: validate Bearer token, return User.

    Drop-in replacement for workshop's ``get_current_user`` dependency.

    Raises:
        HTTPException(401): token missing or invalid.
        RuntimeError: MEMVAULT_OS_TOKEN env var not set (startup misconfiguration).
    """
    expected = _get_expected_token()

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _build_admin_user()


# ---------------------------------------------------------------------------
# Permission stub — workshop compatibility
# ---------------------------------------------------------------------------


def require_permission(permission: str) -> Callable:
    """Dependency factory stub for permission checking.

    In workshop, this enforces RBAC. In standalone mode, the admin token
    grants all permissions, so this always passes.

    Usage (same as workshop):

        @router.get("/blocks")
        async def list_blocks(
            _: None = Depends(require_permission("memvault.read")),
            user: User = Depends(get_current_user),
        ):
            ...
    """

    async def _check(_: User = Depends(get_current_user)) -> None:
        # Admin token → all permissions pass.
        # If you need multi-user support, replace this stub with real RBAC logic.
        pass

    return _check


# ---------------------------------------------------------------------------
# Optional: API key auth (alternative to Bearer header)
# ---------------------------------------------------------------------------


async def get_current_user_from_query(token: str | None = None) -> User:
    """Alternative dependency accepting token as query param ``?token=<value>``.

    Useful for quick testing or CLI-driven access.
    NOT recommended for production — prefer Bearer header.
    """
    expected = _get_expected_token()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token query parameter.",
        )

    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    return _build_admin_user()
