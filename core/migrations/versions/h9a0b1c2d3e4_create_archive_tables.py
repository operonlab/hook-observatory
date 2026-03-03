"""create archive tables for cold data storage

Creates archive tables for the cold-data tier:
  - memvault.blocks_archive    (archived memory blocks)
  - intelflow.reports_archive  (archived research reports)
  - intelflow.briefings_archive (archived daily briefings)

Archive tables mirror their parent tables minus vector columns and HNSW indexes.
Metadata (tags, dates, content) is preserved for ILIKE/B-tree queries.
Content field may hold an S3 reference for COLD-BLOB entries.

Revision ID: h9a0b1c2d3e4
Revises: g8b9c0d1e2f3
Create Date: 2026-02-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "h9a0b1c2d3e4"
down_revision = "g8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- memvault.blocks_archive ---
    op.create_table(
        "blocks_archive",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("source_session", sa.String(64), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("block_type", sa.String(50), nullable=False),
        sa.Column("tags", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("archived_at", sa.Text, nullable=False),
        sa.Column("archive_type", sa.String(20), server_default=sa.text("'cold-archive'")),
        schema="memvault",
    )
    op.create_index("idx_ba_tags", "blocks_archive", ["tags"], schema="memvault", postgresql_using="gin")
    op.create_index("idx_ba_type", "blocks_archive", ["block_type"], schema="memvault")
    op.create_index("idx_ba_created", "blocks_archive", ["created_at"], schema="memvault")
    op.create_index("idx_ba_archived", "blocks_archive", ["archived_at"], schema="memvault")

    # --- intelflow.reports_archive ---
    op.create_table(
        "reports_archive",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sources", JSONB, nullable=True),
        sa.Column("tags", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("skill_name", sa.Text, nullable=True),
        sa.Column("archived_at", sa.Text, nullable=False),
        sa.Column("archive_type", sa.String(20), server_default=sa.text("'cold-archive'")),
        schema="intelflow",
    )
    op.create_index("idx_ra_tags", "reports_archive", ["tags"], schema="intelflow", postgresql_using="gin")
    op.create_index("idx_ra_created", "reports_archive", ["created_at"], schema="intelflow")
    op.create_index("idx_ra_archived", "reports_archive", ["archived_at"], schema="intelflow")

    # --- intelflow.briefings_archive ---
    op.create_table(
        "briefings_archive",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("raw_data", JSONB, nullable=True),
        sa.Column("analyses", JSONB, nullable=True),
        sa.Column("debate", sa.Text, nullable=True),
        sa.Column("archived_at", sa.Text, nullable=False),
        sa.Column("archive_type", sa.String(20), server_default=sa.text("'cold-archive'")),
        schema="intelflow",
    )
    op.create_index("idx_bra_date", "briefings_archive", ["date"], schema="intelflow")
    op.create_index("idx_bra_archived", "briefings_archive", ["archived_at"], schema="intelflow")


def downgrade() -> None:
    op.drop_table("briefings_archive", schema="intelflow")
    op.drop_table("reports_archive", schema="intelflow")
    op.drop_table("blocks_archive", schema="memvault")
