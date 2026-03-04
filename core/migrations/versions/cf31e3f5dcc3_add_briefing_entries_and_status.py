"""add_briefing_entries_and_status

Revision ID: cf31e3f5dcc3
Revises: q8i9j0k1l2m3
Create Date: 2026-03-04 00:18:39.408126
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "cf31e3f5dcc3"
down_revision: str | None = "q8i9j0k1l2m3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intelflow"


def upgrade() -> None:
    # 1. Add status column to briefings
    op.add_column(
        "briefings",
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'completed'"),  # existing rows are completed
            nullable=False,
        ),
        schema=SCHEMA,
    )

    # 2. Create briefing_entries table
    op.create_table(
        "briefing_entries",
        sa.Column("briefing_id", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
        # SpaceScopedModel fields
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("space_id", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["briefing_id"],
            [f"{SCHEMA}.briefings.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("briefing_id", "phase", "key", name="uq_be_briefing_phase_key"),
        schema=SCHEMA,
    )
    op.create_index("idx_be_briefing", "briefing_entries", ["briefing_id"], schema=SCHEMA)
    op.create_index("idx_be_phase", "briefing_entries", ["phase"], schema=SCHEMA)
    op.create_index(
        "ix_intelflow_briefing_entries_space_id",
        "briefing_entries",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intelflow_briefing_entries_deleted_at",
        "briefing_entries",
        ["deleted_at"],
        schema=SCHEMA,
    )

    # HNSW index for semantic search on entries
    op.execute(
        f"""
        CREATE INDEX idx_be_embedding
        ON {SCHEMA}.briefing_entries
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # 3. Set existing briefings to 'completed' status
    op.execute(f"UPDATE {SCHEMA}.briefings SET status = 'completed' WHERE status = 'searching'")

    # 4. Change default for new briefings to 'searching'
    op.alter_column(
        "briefings",
        "status",
        server_default=sa.text("'searching'"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("briefing_entries", schema=SCHEMA)
    op.drop_column("briefings", "status", schema=SCHEMA)
