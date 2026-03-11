"""add KG entity resolution + edge invalidation + traversal indexes

Revision ID: a1b2c3d4e5f7
Revises: z7r8s9t0u1v2
Create Date: 2026-03-11
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "a1b2c3d4e5f7"
down_revision = "z7r8s9t0u1v2"
branch_labels = None
depends_on = None

SCHEMA = "memvault"
EMBEDDING_DIM = 768


def upgrade() -> None:
    # --- entity_canonicals table ---
    op.create_table(
        "entity_canonicals",
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
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("canonical_name", sa.String(500), nullable=False),
        sa.Column(
            "aliases",
            sa.dialects.postgresql.ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "entity_type",
            sa.String(50),
            server_default=sa.text("'concept'"),
        ),
        sa.Column("merge_count", sa.Integer, server_default=sa.text("1")),
        sa.UniqueConstraint(
            "space_id",
            "canonical_name",
            name="uq_entity_canonical_space_name",
        ),
        schema=SCHEMA,
    )

    # Indexes for entity_canonicals
    op.create_index(
        "idx_ec_canonical_name",
        "entity_canonicals",
        ["space_id", "canonical_name"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ec_entity_type",
        "entity_canonicals",
        ["entity_type"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ec_aliases",
        "entity_canonicals",
        ["aliases"],
        schema=SCHEMA,
        postgresql_using="gin",
    )

    # --- Edge invalidation columns on triples ---
    op.add_column(
        "triples",
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column(
            "invalidated_by",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.triples.id"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column(
            "invalidation_reason",
            sa.String(50),
            nullable=True,
        ),
        schema=SCHEMA,
    )

    # --- Entity resolution FK columns on triples ---
    op.add_column(
        "triples",
        sa.Column(
            "canonical_subject_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.entity_canonicals.id"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column(
            "canonical_object_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.entity_canonicals.id"),
            nullable=True,
        ),
        schema=SCHEMA,
    )

    # --- Indexes for traversal and invalidation ---
    op.create_index(
        "idx_triples_object",
        "triples",
        ["object"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_triples_valid",
        "triples",
        ["space_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("invalid_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_triples_valid", table_name="triples", schema=SCHEMA)
    op.drop_index("idx_triples_object", table_name="triples", schema=SCHEMA)
    op.drop_column("triples", "canonical_object_id", schema=SCHEMA)
    op.drop_column("triples", "canonical_subject_id", schema=SCHEMA)
    op.drop_column("triples", "invalidation_reason", schema=SCHEMA)
    op.drop_column("triples", "invalidated_by", schema=SCHEMA)
    op.drop_column("triples", "invalid_at", schema=SCHEMA)
    op.drop_column("triples", "valid_at", schema=SCHEMA)
    op.drop_index("idx_ec_aliases", table_name="entity_canonicals", schema=SCHEMA)
    op.drop_index("idx_ec_entity_type", table_name="entity_canonicals", schema=SCHEMA)
    op.drop_index("idx_ec_canonical_name", table_name="entity_canonicals", schema=SCHEMA)
    op.drop_table("entity_canonicals", schema=SCHEMA)
