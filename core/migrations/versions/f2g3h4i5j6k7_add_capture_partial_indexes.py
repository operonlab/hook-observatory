"""add partial indexes on captures for list + expire queries

Revision ID: a1b2c3d4e5f6
Revises: z7r8s9t0u1v2
Create Date: 2026-03-11

"""

from alembic import op

revision = "f2g3h4i5j6k7"
down_revision = "e1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_captures_space_status",
        "captures",
        ["space_id", "status"],
        schema="shared",
        postgresql_where="deleted_at IS NULL",
        if_not_exists=True,
    )
    op.create_index(
        "ix_captures_expires_at",
        "captures",
        ["expires_at"],
        schema="shared",
        postgresql_where="status = 'pending' AND deleted_at IS NULL",
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_captures_expires_at", table_name="captures", schema="shared")
    op.drop_index("ix_captures_space_status", table_name="captures", schema="shared")
