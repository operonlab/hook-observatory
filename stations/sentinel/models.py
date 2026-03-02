"""SQLAlchemy models for sentinel schema."""

from __future__ import annotations

from sqlalchemy import Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class HealthCheck(Base):
    """Records each health check result."""

    __tablename__ = "health_checks"
    __table_args__ = (
        Index("idx_hc_service", "service"),
        Index("idx_hc_created", "created_at"),
        Index("idx_hc_status", "status"),
        {"schema": "sentinel"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, server_default=text("gen_random_uuid()::text")
    )
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    check_type: Mapped[str] = mapped_column(String(10), nullable=False)  # light / deep
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # healthy / unhealthy / degraded / timeout
    response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("now()::text")
    )


class Incident(Base):
    """Tracks incidents and their resolution."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index("idx_inc_service", "service"),
        Index("idx_inc_status", "status"),
        Index("idx_inc_created", "created_at"),
        {"schema": "sentinel"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, server_default=text("gen_random_uuid()::text")
    )
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'investigating'")
    )  # investigating / identified / repairing / resolved / escalated
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'minor'")
    )  # minor / major / critical
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    repair_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("now()::text")
    )
    resolved_at: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ActiveOperation(Base):
    """Tracks agent-notified operations in progress."""

    __tablename__ = "active_operations"
    __table_args__ = (
        Index("idx_ao_service", "service"),
        Index("idx_ao_agent", "agent_id"),
        {"schema": "sentinel"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, server_default=text("gen_random_uuid()::text")
    )
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    pid: Mapped[int | None] = mapped_column(nullable=True)
    estimated_duration: Mapped[int] = mapped_column(nullable=False, default=300)  # seconds
    created_at: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("now()::text")
    )
    resolved_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    result: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # success / failure / timeout


class Subscription(Base):
    """Webhook subscription for incident notifications."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_sub_active", "active"),
        {"schema": "sentinel"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, server_default=text("gen_random_uuid()::text")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'[\"*\"]'::jsonb")
    )
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("now()::text")
    )
