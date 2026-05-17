"""Pydantic models for auth request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

# --- Auth requests ---


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    status: str | None = None


class UserListQuery(BaseModel):
    page: int = 1
    page_size: int = 20
    status: str | None = None
    search: str | None = None


# --- Auth responses ---


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None = None
    role: str = "user"
    status: str = "active"
    created_at: datetime


class OAuthAccountResponse(BaseModel):
    id: str
    provider: str
    provider_id: str
    email: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    created_at: datetime


class UserDetailResponse(UserResponse):
    oauth_accounts: list[OAuthAccountResponse] = []


class PreferencesUpdate(BaseModel):
    """Partial update — merges into existing preferences JSONB.

    `app_order` is a free-form launcher layout payload (v1 was
    `dict[str, list[str]]`, v2 adds `version`, `folders`, `userFolders`,
    `hidden`). The schema accepts arbitrary nested structures so the
    frontend can evolve its layout shape without backend migrations.
    """

    app_order: dict[str, Any] | None = None


class SessionResponse(BaseModel):
    user: UserResponse
    expires_at: datetime
