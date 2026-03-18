"""Async database engine, session factory, and SQLAlchemy models — anvil schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import config

# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(
    config.database_url,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """FastAPI dependency -- yields an async DB session."""
    async with async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Skill(Base):
    """Skill metadata registry."""

    __tablename__ = "skills"
    __table_args__ = (
        Index("idx_skills_name", "name", unique=True),
        Index("idx_skills_status", "status"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict | list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    io_schema: Mapped[dict | None] = mapped_column(JSONB)
    health_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    domain: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'general'")
    )
    strengths: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    pain_point: Mapped[str | None] = mapped_column(Text)
    triggers: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    body_lines: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    resources: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    guide: Mapped[str | None] = mapped_column(Text)
    health_details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=text("now()")
    )


class Invocation(Base):
    """Every skill invocation via Hook telemetry."""

    __tablename__ = "invocations"
    __table_args__ = (
        Index("idx_invocations_skill", "skill_name"),
        Index("idx_invocations_ts", "timestamp"),
        Index("idx_invocations_session", "session_id"),
        Index(
            "idx_invocations_tool_use_id",
            "tool_use_id",
            unique=True,
            postgresql_where=text("tool_use_id IS NOT NULL"),
        ),
        Index("idx_invocations_category", "category"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    error_message: Mapped[str | None] = mapped_column(Text)
    tool_calls_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    session_id: Mapped[str | None] = mapped_column(String(100))
    agent_model: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    manual_estimate_minutes: Mapped[float | None] = mapped_column(Float)
    time_saved_minutes: Mapped[float | None] = mapped_column(Float)
    tool_use_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'skill'")
    )


class Intent(Base):
    """User skill invocation intents from command-name tags."""

    __tablename__ = "intents"
    __table_args__ = (
        Index("idx_intents_skill", "skill_name"),
        Index("idx_intents_ts", "timestamp"),
        Index("idx_intents_session", "session_id"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    session_id: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSONB)


class SkillVersion(Base):
    """Version snapshots for trend tracking."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        Index("idx_skill_versions_name", "skill_name"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_md_hash: Mapped[str | None] = mapped_column(String(64))
    eval_score: Mapped[float | None] = mapped_column(Float)
    version_meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Evaluation(Base):
    """Three-angle evaluation results."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index("idx_evaluations_skill", "skill_name"),
        Index("idx_evaluations_status", "status"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str | None] = mapped_column(String(50))
    run_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    grading_results: Mapped[dict | None] = mapped_column(JSONB)
    comparator_results: Mapped[dict | None] = mapped_column(JSONB)
    analyzer_report: Mapped[dict | None] = mapped_column(JSONB)
    benchmark_score: Mapped[float | None] = mapped_column(Float)
    benchmark_json: Mapped[dict | None] = mapped_column(JSONB)
    eval_definition_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("anvil.eval_definitions.id"),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'completed'")
    )


class EvalDefinition(Base):
    """Persisted evals.json test definitions."""

    __tablename__ = "eval_definitions"
    __table_args__ = (
        Index("idx_eval_defs_skill", "skill_name", unique=True),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    test_cases: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50))
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=text("now()")
    )


class Correction(Base):
    """Self-correction records."""

    __tablename__ = "corrections"
    __table_args__ = (
        Index("idx_corrections_skill", "skill_name"),
        Index("idx_corrections_status", "status"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_score: Mapped[float | None] = mapped_column(Float)
    after_score: Mapped[float | None] = mapped_column(Float)
    diff_content: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'proposed'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LifecycleRun(Base):
    """Skill lifecycle pipeline run record."""

    __tablename__ = "lifecycle_runs"
    __table_args__ = (
        Index("idx_lifecycle_runs_run_id", "run_id", unique=True),
        Index("idx_lifecycle_runs_status", "status"),
        Index("idx_lifecycle_runs_started", "started_at"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'running'")
    )
    trigger: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'manual'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Phase results: {"test": {"status": "ok", "duration_ms": 5000}, ...}
    phases: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # Test metrics
    total_skills: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    test_passed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    test_partial: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    test_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Security metrics
    sec_clean: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sec_warned: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sec_blocked: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Optimize metrics
    optimized: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    changes_applied: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Detailed per-skill results
    test_details: Mapped[dict | None] = mapped_column(JSONB)
    security_details: Mapped[dict | None] = mapped_column(JSONB)
    catalog_snapshot: Mapped[dict | None] = mapped_column(JSONB)

    # Skipped/errors
    skipped_phases: Mapped[dict | list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    errors: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class SkillEdge(Base):
    """Directed relationship between two skills in the knowledge graph."""

    __tablename__ = "skill_edges"
    __table_args__ = (
        Index("idx_skill_edges_source", "source"),
        Index("idx_skill_edges_target", "target"),
        {"schema": "anvil"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
    description: Mapped[str | None] = mapped_column(Text)
