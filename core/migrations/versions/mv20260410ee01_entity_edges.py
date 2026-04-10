"""entity_edges: multi-signal weighted edges between canonical entities.

Five association signals (cooccurrence, session_overlap, adamic_adar,
type_affinity, semantic_similarity) compose into a single composite_weight
used by Leiden community detection and CascadeRecall.

Inspired by nashsu/llm_wiki four-signal association model.

Revision ID: mv20260410ee01
Revises: z7r8s9t0u1v2
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from alembic import op

revision = "mv20260410ee01"
down_revision = "z7r8s9t0u1v2"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.create_table(
        "entity_edges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # Edge endpoints (normalized: entity_a_id < entity_b_id)
        sa.Column(
            "entity_a_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.entity_canonicals.id"),
            nullable=False,
        ),
        sa.Column(
            "entity_b_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.entity_canonicals.id"),
            nullable=False,
        ),
        # Five signals
        sa.Column("cooccurrence_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("session_overlap", sa.Float, server_default=sa.text("0.0")),
        sa.Column("adamic_adar", sa.Float, server_default=sa.text("0.0")),
        sa.Column("type_affinity", sa.Float, server_default=sa.text("0.0")),
        sa.Column("semantic_similarity", sa.Float, server_default=sa.text("0.0")),
        # Composite
        sa.Column("composite_weight", sa.Float, server_default=sa.text("0.0")),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.UniqueConstraint(
            "space_id", "entity_a_id", "entity_b_id", name="uq_entity_edge_pair"
        ),
        sa.CheckConstraint("entity_a_id < entity_b_id", name="chk_edge_order"),
        schema=SCHEMA,
    )

    op.create_index(
        "idx_ee_weight",
        "entity_edges",
        ["composite_weight"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ee_entities",
        "entity_edges",
        ["entity_a_id", "entity_b_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ee_space",
        "entity_edges",
        ["space_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_ee_space", "entity_edges", schema=SCHEMA)
    op.drop_index("idx_ee_entities", "entity_edges", schema=SCHEMA)
    op.drop_index("idx_ee_weight", "entity_edges", schema=SCHEMA)
    op.drop_table("entity_edges", schema=SCHEMA)
