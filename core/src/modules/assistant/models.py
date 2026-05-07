"""Assistant module models — QaLog."""

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import GlobalModel


class QaLog(GlobalModel):
    """Persisted Q&A log for analytics and quality tracking."""

    __tablename__ = "qa_log"
    __table_args__ = (
        Index("idx_qa_log_session", "session_id"),
        Index("idx_qa_log_flagged", "flagged"),
        {"schema": "assistant"},
    )

    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, server_default="false", index=False)
    flag_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
