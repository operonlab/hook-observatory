"""Memvault Knowledge Graph ORM models — Triples, Communities, Summaries, Attitudes, Skills.

Knowledge Graph layers (GraphRAG / HiRAG inspired):
  L0 — Triple           : raw subject-predicate-object facts (graph edges)
  L0 — EntityCanonical  : deduplicated entity nodes (graph vertices)
  L1 — Community        : Leiden graph communities at multiple resolution levels
  L2 — CommunitySummary : pre-generated LLM summaries per community
  Attitude Layer        — AttitudeFact : versioned attitude/belief facts
  Skill Layer           — SkillInvocation : per-session skill usage records

References: GraphRAG (2404.16130), HiRAG (2503.10150), LeanRAG (2508.10391)
All tables live in the `memvault` PostgreSQL schema.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import SpaceScopedModel

from .models import SCHEMA

# ---------------------------------------------------------------------------
# L0 — Triple
# ---------------------------------------------------------------------------


class EntityCanonical(SpaceScopedModel):
    """Canonical entity node — deduplicates subject/object strings across triples."""

    __tablename__ = "entity_canonicals"
    __table_args__ = (
        Index("idx_ec_canonical_name", "space_id", "canonical_name"),
        Index("idx_ec_entity_type", "entity_type"),
        Index("idx_ec_aliases", "aliases", postgresql_using="gin"),
        UniqueConstraint(
            "space_id",
            "canonical_name",
            name="uq_entity_canonical_space_name",
        ),
        {"schema": SCHEMA},
    )

    canonical_name: Mapped[str] = mapped_column(String(500))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    entity_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'concept'")
    )  # concept | tool | person | org | language
    merge_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class Triple(SpaceScopedModel):
    """A single subject-predicate-object fact extracted from a session (Knowledge L0)."""

    __tablename__ = "triples"
    __table_args__ = (
        Index("idx_triples_session", "source_session"),
        Index("idx_triples_predicate", "predicate"),
        Index("idx_triples_subject", "subject"),
        Index("idx_triples_object", "object"),
        Index(
            "idx_triples_valid",
            "space_id",
            postgresql_where=text("invalid_at IS NULL"),
        ),
        UniqueConstraint(
            "space_id",
            "source_session",
            "subject",
            "predicate",
            "object",
            name="uq_triples_space_session_spo",
        ),
        {"schema": SCHEMA},
    )

    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str] = mapped_column(String(500))
    predicate: Mapped[str] = mapped_column(String(100))
    object: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Edge invalidation (Graphiti-inspired temporal validity)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.triples.id"), nullable=True
    )  # ID of newer triple that superseded this one; NULL = valid
    invalidation_reason: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # contradiction | manual | correction
    # Entity resolution FK (canonical entity references)
    canonical_subject_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.entity_canonicals.id"), nullable=True
    )
    canonical_object_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.entity_canonicals.id"), nullable=True
    )


# ---------------------------------------------------------------------------
# L1 — Community (Leiden graph community detection)
# ---------------------------------------------------------------------------


class Community(SpaceScopedModel):
    """A graph community of densely interconnected entities (Knowledge L1).

    Detected via Leiden algorithm on the entity co-occurrence graph.
    Multiple resolution levels form a hierarchy:
      Level 0 = fine-grained (~100-200 communities)
      Level 1 = medium (~20-40)
      Level 2 = coarse (~5-10 top-level themes)
    """

    __tablename__ = "communities"
    __table_args__ = (
        Index("idx_communities_level", "resolution_level"),
        Index("idx_communities_parent", "parent_community_id"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(300))
    resolution_level: Mapped[int] = mapped_column(Integer)  # 0=fine, 1=medium, 2=coarse
    size: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    entity_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_entities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_predicates: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_community_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.communities.id"), nullable=True
    )
    generation_batch: Mapped[str | None] = mapped_column(String(32), nullable=True)
    modularity_score: Mapped[float | None] = mapped_column(Float, nullable=True)


# ---------------------------------------------------------------------------
# L1 — CommunityTriple (M2M: community ↔ triple membership)
# ---------------------------------------------------------------------------


class CommunityTriple(SpaceScopedModel):
    """Maps triples to their community (hard partition from Leiden)."""

    __tablename__ = "community_triples"
    __table_args__ = (
        Index("idx_community_triples_community", "community_id"),
        Index("idx_community_triples_triple", "triple_id"),
        {"schema": SCHEMA},
    )

    community_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.communities.id"), nullable=False
    )
    triple_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.triples.id"), nullable=False
    )


# ---------------------------------------------------------------------------
# L2 — CommunitySummary (pre-generated LLM summaries)
# ---------------------------------------------------------------------------


class CommunitySummary(SpaceScopedModel):
    """Pre-generated LLM summary for a community (Knowledge L2).

    Generated daily during synthesis. One summary per community.
    Queried directly by CascadeRecall (zero LLM latency at recall time).
    """

    __tablename__ = "community_summaries"
    __table_args__ = (
        Index("idx_community_summaries_community", "community_id"),
        {"schema": SCHEMA},
    )

    community_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.communities.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text)
    key_findings: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    representative_triples: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )  # top 3-5 triple texts
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_batch: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# Attitude Layer — AttitudeFact
# ---------------------------------------------------------------------------


class AttitudeFact(SpaceScopedModel):
    """A versioned attitude or belief fact — NULL superseded_by means current version."""

    __tablename__ = "attitude_facts"
    __table_args__ = (
        Index("idx_attitude_facts_category", "category"),
        Index(
            "idx_attitude_facts_current",
            "space_id",
            postgresql_where=text("superseded_by IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    fact: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(20))  # ADD / UPDATE / NOOP
    confidence: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    source_sessions: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.attitude_facts.id"),
        nullable=True,
    )  # NULL = current version
    previous_version: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.attitude_facts.id"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# Skill Layer — SkillInvocation
# ---------------------------------------------------------------------------


class SkillInvocation(SpaceScopedModel):
    """A record of a single skill invocation within a session."""

    __tablename__ = "skill_invocations"
    __table_args__ = (
        Index("idx_skill_invocations_skill_name", "skill_name"),
        Index("idx_skill_invocations_session", "source_session"),
        Index(
            "idx_skill_invocations_recent",
            "created_at",
            postgresql_where=text("created_at > now() - interval '30 days'"),
        ),
        UniqueConstraint(
            "space_id",
            "skill_name",
            "source_session",
            "invoked_at",
            name="uq_skill_invocations_space_skill_session_at",
        ),
        {"schema": SCHEMA},
    )

    skill_name: Mapped[str] = mapped_column(String(200))
    source_session: Mapped[str] = mapped_column(String(64))
    cwd: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20), server_default=text("'unknown'"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
