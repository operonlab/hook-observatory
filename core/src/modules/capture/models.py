"""Capture model — shared.captures table."""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base, SoftDeleteMixin, TimestampMixin

SCHEMA = "shared"


class Capture(TimestampMixin, SoftDeleteMixin, Base):
    """A captured intent fragment awaiting enrichment and promotion."""

    __tablename__ = "captures"
    __table_args__ = ({"schema": SCHEMA},)

    space_id: Mapped[str] = mapped_column(String(32), index=True)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    module: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    completeness: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0"
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )  # pending / promoted / expired
    promoted_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
