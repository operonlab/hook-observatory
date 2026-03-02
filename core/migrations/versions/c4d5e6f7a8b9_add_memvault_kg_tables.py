"""add memvault knowledge graph tables

Revision ID: c4d5e6f7a8b9
Revises: 2bb21e53cb53
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "c4d5e6f7a8b9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # --- triples ---
    op.create_table(
        "triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_session", sa.String(64), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("predicate", sa.String(100), nullable=False),
        sa.Column("object", sa.Text, nullable=False),
        sa.Column("topic", sa.String(500), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.UniqueConstraint(
            "space_id",
            "source_session",
            "subject",
            "predicate",
            "object",
            name="uq_triples_space_session_spo",
        ),
        schema=SCHEMA,
    )
    op.create_index("idx_triples_space", "triples", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_triples_session", "triples", ["source_session"], schema=SCHEMA
    )
    op.create_index("idx_triples_predicate", "triples", ["predicate"], schema=SCHEMA)
    op.create_index("idx_triples_subject", "triples", ["subject"], schema=SCHEMA)
    op.execute(
        f"""
        CREATE INDEX idx_triples_embedding
        ON {SCHEMA}.triples
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # --- clusters ---
    op.create_table(
        "clusters",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "size", sa.Integer, server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "top_subjects",
            sa.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "top_predicates",
            sa.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "top_objects",
            sa.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "verdict",
            sa.String(20),
            server_default=sa.text("'UNVERIFIED'"),
            nullable=False,
        ),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_clusters_space", "clusters", ["space_id"], schema=SCHEMA)

    # --- cluster_triples ---
    op.create_table(
        "cluster_triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cluster_id", sa.String(32), nullable=False),
        sa.Column("triple_id", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            [f"{SCHEMA}.clusters.id"],
            name="fk_cluster_triples_cluster",
        ),
        sa.ForeignKeyConstraint(
            ["triple_id"],
            [f"{SCHEMA}.triples.id"],
            name="fk_cluster_triples_triple",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_cluster_triples_space", "cluster_triples", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_cluster_triples_cluster",
        "cluster_triples",
        ["cluster_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_cluster_triples_triple",
        "cluster_triples",
        ["triple_id"],
        schema=SCHEMA,
    )

    # --- wisdom_nodes ---
    op.create_table(
        "wisdom_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("wisdom", sa.Text, nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("bridge_entity", sa.String(200), nullable=False),
        sa.Column(
            "cluster_ids",
            sa.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("evidence_count", sa.Integer, nullable=True),
        sa.Column(
            "tags",
            sa.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "verified",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_wisdom_nodes_space", "wisdom_nodes", ["space_id"], schema=SCHEMA
    )

    # --- attitude_facts ---
    op.create_table(
        "attitude_facts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("fact", sa.Text, nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column(
            "confidence",
            sa.Float,
            server_default=sa.text("0.5"),
            nullable=False,
        ),
        sa.Column(
            "source_sessions",
            sa.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("superseded_by", sa.String(32), nullable=True),
        sa.Column("previous_version", sa.String(32), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            [f"{SCHEMA}.attitude_facts.id"],
            name="fk_attitude_facts_superseded_by",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version"],
            [f"{SCHEMA}.attitude_facts.id"],
            name="fk_attitude_facts_previous_version",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_attitude_facts_space", "attitude_facts", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_attitude_facts_category",
        "attitude_facts",
        ["category"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX idx_attitude_facts_current
        ON {SCHEMA}.attitude_facts (space_id)
        WHERE superseded_by IS NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_attitude_facts_embedding
        ON {SCHEMA}.attitude_facts
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # --- skill_invocations ---
    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("source_session", sa.String(64), nullable=False),
        sa.Column("cwd", sa.String(500), nullable=True),
        sa.Column("invoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outcome",
            sa.String(20),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.UniqueConstraint(
            "space_id",
            "skill_name",
            "source_session",
            "invoked_at",
            name="uq_skill_invocations_space_skill_session_time",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_skill_invocations_space",
        "skill_invocations",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_skill_invocations_skill_name",
        "skill_invocations",
        ["skill_name"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_skill_invocations_session",
        "skill_invocations",
        ["source_session"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("skill_invocations", schema=SCHEMA)
    op.drop_table("attitude_facts", schema=SCHEMA)
    op.drop_table("wisdom_nodes", schema=SCHEMA)
    op.drop_table("cluster_triples", schema=SCHEMA)
    op.drop_table("clusters", schema=SCHEMA)
    op.drop_table("triples", schema=SCHEMA)
