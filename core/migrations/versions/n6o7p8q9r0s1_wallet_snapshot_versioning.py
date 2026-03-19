"""Wallet snapshot versioning — add version, batch_id, metadata_json.

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r2
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r2"
branch_labels = None
depends_on = None


def upgrade():
    # Add columns
    op.add_column(
        "wallet_snapshots",
        sa.Column("version", sa.Integer(), nullable=True),
        schema="finance",
    )
    op.add_column(
        "wallet_snapshots",
        sa.Column("batch_id", sa.String(32), nullable=True),
        schema="finance",
    )
    op.add_column(
        "wallet_snapshots",
        sa.Column("metadata_json", JSONB(), nullable=True),
        schema="finance",
    )

    # Backfill version using window function
    op.execute(
        """
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY wallet_id ORDER BY synced_at ASC
            ) AS rn
            FROM finance.wallet_snapshots
        )
        UPDATE finance.wallet_snapshots s
        SET version = numbered.rn
        FROM numbered
        WHERE s.id = numbered.id
    """
    )

    # Set NOT NULL
    op.alter_column(
        "wallet_snapshots", "version", nullable=False, schema="finance"
    )

    # Create indexes
    op.create_index(
        "idx_snapshot_wallet_version",
        "wallet_snapshots",
        ["wallet_id", "version"],
        unique=True,
        schema="finance",
    )
    op.create_index(
        "idx_snapshot_batch",
        "wallet_snapshots",
        ["batch_id"],
        schema="finance",
        postgresql_where=sa.text("batch_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "idx_snapshot_batch", table_name="wallet_snapshots", schema="finance"
    )
    op.drop_index(
        "idx_snapshot_wallet_version",
        table_name="wallet_snapshots",
        schema="finance",
    )
    op.drop_column("wallet_snapshots", "metadata_json", schema="finance")
    op.drop_column("wallet_snapshots", "batch_id", schema="finance")
    op.drop_column("wallet_snapshots", "version", schema="finance")
