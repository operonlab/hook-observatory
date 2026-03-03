"""Notification models — PushSubscription + NotificationLog."""

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import GlobalModel


class PushSubscription(GlobalModel):
    """A browser push subscription tied to a user + device."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        Index("idx_push_sub_user", "user_id"),
        Index("idx_push_sub_active", "active"),
        {"schema": "notification"},
    )

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_scope: Mapped[str] = mapped_column(String(100), server_default="'/v2/'")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    preferences: Mapped[dict] = mapped_column(
        JSONB,
        server_default='\'{"sentinel":true,"system":true,"finance":true,"taskflow":true,"intelflow":true,"agent":true}\'',
    )


class NotificationLog(GlobalModel):
    """Log of sent push notifications for analytics and debugging."""

    __tablename__ = "notification_log"
    __table_args__ = (
        Index("idx_notif_log_user", "user_id"),
        Index("idx_notif_log_category", "category"),
        {"schema": "notification"},
    )

    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, server_default="''")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipients: Mapped[int] = mapped_column(Integer, server_default="0")
    delivered: Mapped[int] = mapped_column(Integer, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, server_default="0")
    source_event: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
