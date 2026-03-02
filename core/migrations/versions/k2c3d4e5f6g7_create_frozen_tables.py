"""create frozen tables for four-tier data lifecycle

Creates frozen tables for legal retention tier:
  - memvault.blocks_frozen     (frozen memory blocks metadata + S3 ref)
  - intelflow.reports_frozen   (frozen research reports metadata + S3 ref)
  - intelflow.briefings_frozen (frozen briefings metadata + S3 ref)

Frozen tables store minimal metadata in PG while full content lives in S3.
Content is zstd-compressed JSON with SHA-256 integrity hash.

Revision ID: k2c3d4e5f6g7
Revises: j1b2c3d4e5f6
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "k2c3d4e5f6g7"
down_revision = "j1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- memvault.blocks_frozen ---
    op.create_table(
        "blocks_frozen",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("block_type", sa.String(50), nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("source_session", sa.String(64), nullable=True),
        schema="memvault",
    )
    op.create_index(
        "idx_bf_space_created",
        "blocks_frozen",
        ["space_id", "created_at"],
        schema="memvault",
    )
    op.create_index(
        "idx_bf_tags",
        "blocks_frozen",
        ["tags"],
        schema="memvault",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_bf_frozen",
        "blocks_frozen",
        ["frozen_at"],
        schema="memvault",
    )
    op.create_index(
        "idx_bf_type",
        "blocks_frozen",
        ["block_type"],
        schema="memvault",
    )

    # --- intelflow.reports_frozen ---
    op.create_table(
        "reports_frozen",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("skill_name", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        schema="intelflow",
    )
    op.create_index(
        "idx_rf_space_created",
        "reports_frozen",
        ["space_id", "created_at"],
        schema="intelflow",
    )
    op.create_index(
        "idx_rf_tags",
        "reports_frozen",
        ["tags"],
        schema="intelflow",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_rf_frozen",
        "reports_frozen",
        ["frozen_at"],
        schema="intelflow",
    )

    # --- intelflow.briefings_frozen ---
    op.create_table(
        "briefings_frozen",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("domain", sa.Text, nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        schema="intelflow",
    )
    op.create_index(
        "idx_brf_date",
        "briefings_frozen",
        ["date"],
        schema="intelflow",
    )
    op.create_index(
        "idx_brf_frozen",
        "briefings_frozen",
        ["frozen_at"],
        schema="intelflow",
    )


def downgrade() -> None:
    op.drop_table("briefings_frozen", schema="intelflow")
    op.drop_table("reports_frozen", schema="intelflow")
    op.drop_table("blocks_frozen", schema="memvault")
