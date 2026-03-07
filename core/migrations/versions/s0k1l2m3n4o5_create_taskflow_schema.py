"""create taskflow schema — tasks + task_updates

Revision ID: s0k1l2m3n4o5
Revises: r9j0k1l2m3n4
Create Date: 2026-03-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# revision identifiers, used by Alembic.
revision: str = "s0k1l2m3n4o5"
down_revision: str | None = "r9j0k1l2m3n4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "taskflow"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("project", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="todo"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.Text, nullable=False, server_default="medium"),
        sa.Column("estimated_hours", sa.Float, nullable=True),
        sa.Column("actual_hours", sa.Float, nullable=True),
        sa.Column("recurrence", JSONB, nullable=True),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        sa.Column(
            "parent_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # Indexes
    op.create_index(
        "idx_task_space_status",
        "tasks",
        ["space_id", "status"],
        schema=SCHEMA,
    )
    op.create_index("idx_task_parent", "tasks", ["parent_id"], schema=SCHEMA)
    op.create_index("idx_task_deleted", "tasks", ["deleted_at"], schema=SCHEMA)
    op.create_index(
        "idx_task_due_date",
        "tasks",
        ["space_id", "due_date"],
        schema=SCHEMA,
        postgresql_where=sa.text(
            "due_date IS NOT NULL AND status NOT IN ('done', 'cancelled')"
        ),
    )

    op.create_table(
        "task_updates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("old_status", sa.Text, nullable=True),
        sa.Column("new_status", sa.Text, nullable=True),
        sa.Column("hours_spent", sa.Float, nullable=True),
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
        schema=SCHEMA,
    )

    op.create_index(
        "idx_task_update_task",
        "task_updates",
        ["task_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("task_updates", schema=SCHEMA)
    op.drop_table("tasks", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
