"""Capture models — shared.captures + shared.capture_enrichments."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    group_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    promoted_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    enrichments: Mapped[list["CaptureEnrichment"]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )


class CaptureEnrichment(Base):
    """Audit trail for each enrichment step on a capture."""

    __tablename__ = "capture_enrichments"
    __table_args__ = ({"schema": SCHEMA},)

    capture_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.captures.id", ondelete="CASCADE"),
        index=True,
    )
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    previous_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    capture: Mapped["Capture"] = relationship(back_populates="enrichments")
