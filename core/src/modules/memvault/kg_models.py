"""Memvault Knowledge Graph ORM models — Triples, Clusters, Wisdom, Attitudes, Skills.

Knowledge Graph layers:
  L0 — Triple      : raw subject-predicate-object facts extracted from sessions
  L1 — Cluster     : GMM-clustered triple groups with summary/verdict
  L2 — WisdomNode  : cross-cluster insight bridges (high-level learnings)
  Attitude Layer   — AttitudeFact : versioned attitude/belief facts
  Skill Layer      — SkillInvocation : per-session skill usage records

All tables live in the `memvault` PostgreSQL schema.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
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

from src.shared.models import Base, SpaceScopedModel

from .models import EMBEDDING_DIM, SCHEMA


class TripleEmbedding(Base):
    """Separated embedding vector for Triple — allows independent lifecycle management."""

    __tablename__ = "triple_embeddings"
    __table_args__ = (
        Index(
            "idx_triple_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": SCHEMA},
    )

    triple_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.triples.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


# ---------------------------------------------------------------------------
# L0 — Triple
# ---------------------------------------------------------------------------


class EntityCanonical(SpaceScopedModel):
    """Canonical entity node — deduplicates subject/object strings across triples."""

    __tablename__ = "entity_canonicals"
    __table_args__ = (
        Index("idx_ec_canonical_name", "space_id", "canonical_name"),
        Index("idx_ec_entity_type", "entity_type"),
        Index(
            "idx_ec_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
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
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
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
        Index(
            "idx_triples_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "idx_triples_embedding_recent",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("created_at > now() - interval '90 days'"),
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
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


# ---------------------------------------------------------------------------
# L1 — Cluster
# ---------------------------------------------------------------------------


class Cluster(SpaceScopedModel):
    """A GMM-derived cluster grouping related triples (Knowledge L1)."""

    __tablename__ = "clusters"
    __table_args__ = ({"schema": SCHEMA},)

    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    top_subjects: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_predicates: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_objects: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # "情境→判斷→結果" pattern
    verdict: Mapped[str] = mapped_column(String(20), server_default=text("'UNVERIFIED'"))
    generation_batch: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# L1 — ClusterTriple (M2M)
# ---------------------------------------------------------------------------


class ClusterTriple(SpaceScopedModel):
    """Many-to-many join between Cluster and Triple with GMM posterior confidence."""

    __tablename__ = "cluster_triples"
    __table_args__ = (
        Index("idx_cluster_triples_cluster", "cluster_id"),
        Index("idx_cluster_triples_triple", "triple_id"),
        {"schema": SCHEMA},
    )

    cluster_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.clusters.id"), nullable=False
    )
    triple_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.triples.id"), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # GMM posterior probability


# ---------------------------------------------------------------------------
# L2 — WisdomNode
# ---------------------------------------------------------------------------


class WisdomNode(SpaceScopedModel):
    """A cross-cluster insight that bridges multiple clusters (Knowledge L2)."""

    __tablename__ = "wisdom_nodes"
    __table_args__ = ({"schema": SCHEMA},)

    wisdom: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20))  # HIGH / MEDIUM / LOW
    bridge_entity: Mapped[str] = mapped_column(String(200))
    cluster_ids: Mapped[list[str]] = mapped_column(ARRAY(Text))
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


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
        Index(
            "idx_attitude_facts_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
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
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


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
