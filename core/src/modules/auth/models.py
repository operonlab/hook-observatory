"""Auth ORM models — users, oauth_accounts, sessions in the `auth` schema."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import GlobalModel

SCHEMA = "auth"


class User(GlobalModel):
    """Platform user — email/password + OAuth authentication."""

    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_email", "email", unique=True),
        {"schema": SCHEMA},
    )

    email: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(50), server_default="user")
    status: Mapped[str] = mapped_column(String(50), server_default="pending")


class OAuthAccount(GlobalModel):
    """Linked OAuth provider account."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_oauth_provider_id"),
        Index("idx_oauth_user", "user_id"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("auth.users.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    provider_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Session(GlobalModel):
    """DB-backed session record (Redis is the hot cache)."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_token", "token_hash", unique=True),
        {"schema": SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("auth.users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
