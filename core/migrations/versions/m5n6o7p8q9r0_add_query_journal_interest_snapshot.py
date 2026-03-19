"""add query_journal and interest_snapshots tables for closed-loop learning

Revision ID: m5n6o7p8q9r0
Revises: l4m5n6o7p8q9
Create Date: 2026-03-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "m5n6o7p8q9r0"
down_revision: str | None = "l4m5n6o7p8q9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── query_journal ──────────────────────────────────────────────────────────
    op.create_table(
        "query_journal",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("routing_intent", sa.String(50), nullable=True),
        sa.Column("routing_confidence", sa.Float(), nullable=True),
        sa.Column(
            "layers_searched",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "result_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("evaluation_verdict", sa.String(20), nullable=True),
        sa.Column("evaluation_score", sa.Float(), nullable=True),
        sa.Column(
            "top_entity_ids",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Index("idx_qj_query_hash", "query_hash"),
        sa.Index("idx_qj_space_created", "space_id", "created_at"),
        sa.Index("idx_qj_routing_intent", "routing_intent"),
        schema="memvault",
    )

    # ── interest_snapshots ─────────────────────────────────────────────────────
    op.create_table(
        "interest_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("top_intents", JSONB(), nullable=True),
        sa.Column("top_entities", JSONB(), nullable=True),
        sa.Column("top_communities", JSONB(), nullable=True),
        sa.Column("knowledge_gaps", JSONB(), nullable=True),
        sa.Column("attention_profile", JSONB(), nullable=True),
        sa.Column(
            "query_volume",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("avg_result_quality", sa.Float(), nullable=True),
        sa.Index("idx_is_space_date", "space_id", "snapshot_date"),
        sa.Index("idx_is_period", "period"),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_table("interest_snapshots", schema="memvault")
    op.drop_table("query_journal", schema="memvault")
