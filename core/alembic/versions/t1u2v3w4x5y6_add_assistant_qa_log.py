"""Add assistant.qa_log table for QA persistence.

Revision ID: t1u2v3w4x5y6
Revises: s1t2u3v4w5x6
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op

revision = "t1u2v3w4x5y6"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None

SCHEMA = "assistant"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "qa_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("session_id", sa.String(32), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False, server_default="''"),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("flagged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("flag_reason", sa.String(500), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_qa_log_session", "qa_log", ["session_id"], schema=SCHEMA)
    op.create_index("idx_qa_log_flagged", "qa_log", ["flagged"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("idx_qa_log_flagged", table_name="qa_log", schema=SCHEMA)
    op.drop_index("idx_qa_log_session", table_name="qa_log", schema=SCHEMA)
    op.drop_table("qa_log", schema=SCHEMA)
