"""Shared FastAPI dependencies."""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import get_db as _get_db
from src.shared.errors import ForbiddenError


async def get_db() -> AsyncSession:
    """Alias for database.get_db — use in Depends()."""
    async for session in _get_db():
        yield session


def get_current_user(request: Request) -> dict:
    """Extract authenticated user from session. Raises 401 if absent."""
    from src.modules.auth.deps import get_current_user as _auth_get_current_user
    return _auth_get_current_user(request)


def require_permission(permission: str):
    """Dependency factory: check RBAC permission."""
    from src.modules.auth.permissions import has_permission

    def _check(request: Request) -> dict:
        user = get_current_user(request)
        if not has_permission(user.get("role", "guest"), permission):
            raise ForbiddenError(
                f"Permission denied: {permission}",
                code=f"{permission.split('.')[0]}.forbidden",
            )
        return user

    return Depends(_check)
