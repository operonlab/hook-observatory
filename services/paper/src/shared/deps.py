"""Shared dependencies for paper-svc (simplified from core)."""

from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def require_permission(perm: str):
    """Simplified permission check for standalone microservice.

    In dev/auth_bypass mode, allows all requests.
    In production, checks X-Internal-Key header.
    """

    async def _check(x_internal_key: str = Header("", alias="X-Internal-Key")):
        if settings.auth_bypass:
            return {}
        if settings.internal_api_key and x_internal_key == settings.internal_api_key:
            return {}
        raise HTTPException(status_code=403, detail="Permission denied")

    return Depends(_check)
