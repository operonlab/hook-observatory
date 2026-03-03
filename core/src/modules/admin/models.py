"""Admin ORM models — audit logs.

All tables live in the `admin` PostgreSQL schema.
"""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base, TimestampMixin

SCHEMA = "admin"


class AuditLog(TimestampMixin, Base):
    """Immutable audit trail — records every CUD operation across modules."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_entity", "module", "entity_type", "entity_id"),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_created", text("created_at DESC")),
        Index("idx_audit_space", "space_id"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # created / updated / deleted / restored / purged
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
