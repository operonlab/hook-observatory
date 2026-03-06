import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _today():
    return date.today()


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class DailyRun(Base):
    """Track daily survey run status for smart notification."""

    __tablename__ = "daily_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, default=_today)
    attend_url: Mapped[str | None] = mapped_column(Text)
    quiz_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    # pending | running | completed | failed
    result_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # attendance | quiz
    raw_content: Mapped[str | None] = mapped_column(Text)
    company_options: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    questions: Mapped[list["Question"]] = relationship(back_populates="survey", cascade="all")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="survey", cascade="all")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    survey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("surveys.id"), nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    survey: Mapped["Survey"] = relationship(back_populates="questions")


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    submissions: Mapped[list["Submission"]] = relationship(back_populates="person", cascade="all")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("survey_id", "person_id", name="uq_survey_person"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    survey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("surveys.id"), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # success | failed | skipped
    score: Mapped[int | None] = mapped_column(Integer)
    answers_snapshot: Mapped[dict | None] = mapped_column(JSONB)  # {subject_id: answer_text}
    error_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    survey: Mapped["Survey"] = relationship(back_populates="submissions")
    person: Mapped["Person"] = relationship(back_populates="submissions")
