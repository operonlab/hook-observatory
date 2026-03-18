"""create memvault search_feedback table

Revision ID: h0i1j2k3l4m5
Revises: g9h0i1j2k3l4
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op

revision = "h0i1j2k3l4m5"
down_revision = "g9h0i1j2k3l4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_feedback",
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
        sa.Column("entity_id", sa.String(32), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("signal", sa.String(20), nullable=False),
        sa.Column(
            "feedback_source",
            sa.String(20),
            server_default=sa.text("'agent'"),
            nullable=False,
        ),
        sa.Index("idx_sf_entity", "entity_id"),
        sa.Index("idx_sf_query_hash", "query_hash"),
        sa.Index("idx_sf_entity_signal", "entity_id", "signal"),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_table("search_feedback", schema="memvault")
