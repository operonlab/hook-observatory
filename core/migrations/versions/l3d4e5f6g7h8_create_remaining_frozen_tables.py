"""create frozen tables for finance, taskflow, ideagraph

Extends the four-tier lifecycle to remaining domain modules.
P3 implementation: frozen tables for modules not covered in k2c3d4e5f6g7.

Revision ID: l3d4e5f6g7h8
Revises: k2c3d4e5f6g7
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "l3d4e5f6g7h8"
down_revision = "k2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- finance.transactions_frozen ---
    op.create_table(
        "transactions_frozen",
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
        sa.Column("wallet_id", sa.String(32), nullable=True),
        sa.Column(
            "category_path", sa.Text, nullable=True,
        ),
        sa.Column(
            "amount", sa.Numeric(15, 4), nullable=True,
        ),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column(
            "content_hash", sa.String(64), nullable=False,
        ),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        schema="finance",
    )
    op.create_index(
        "idx_txf_space_created",
        "transactions_frozen",
        ["space_id", "created_at"],
        schema="finance",
    )
    op.create_index(
        "idx_txf_tags",
        "transactions_frozen",
        ["tags"],
        schema="finance",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_txf_frozen",
        "transactions_frozen",
        ["frozen_at"],
        schema="finance",
    )

    # --- taskflow.tasks_frozen ---
    op.create_table(
        "tasks_frozen",
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
        sa.Column("task_type", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column(
            "content_hash", sa.String(64), nullable=False,
        ),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        schema="taskflow",
    )
    op.create_index(
        "idx_tkf_space_created",
        "tasks_frozen",
        ["space_id", "created_at"],
        schema="taskflow",
    )
    op.create_index(
        "idx_tkf_tags",
        "tasks_frozen",
        ["tags"],
        schema="taskflow",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_tkf_frozen",
        "tasks_frozen",
        ["frozen_at"],
        schema="taskflow",
    )

    # --- ideagraph.sparks_frozen ---
    op.create_table(
        "sparks_frozen",
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
        sa.Column("spark_type", sa.String(50), nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=False),
        sa.Column(
            "content_hash", sa.String(64), nullable=False,
        ),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        schema="ideagraph",
    )
    op.create_index(
        "idx_sf_space_created",
        "sparks_frozen",
        ["space_id", "created_at"],
        schema="ideagraph",
    )
    op.create_index(
        "idx_sf_tags",
        "sparks_frozen",
        ["tags"],
        schema="ideagraph",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_sf_frozen",
        "sparks_frozen",
        ["frozen_at"],
        schema="ideagraph",
    )


def downgrade() -> None:
    op.drop_table("sparks_frozen", schema="ideagraph")
    op.drop_table("tasks_frozen", schema="taskflow")
    op.drop_table("transactions_frozen", schema="finance")
