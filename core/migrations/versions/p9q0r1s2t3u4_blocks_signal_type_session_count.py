"""blocks signal_type + session_count: schema drift fix

Revision ID: p9q0r1s2t3u4
Revises: n7o8p9q0r1s2
Create Date: 2026-05-08

修復既有 schema drift：blocks ORM (models.py:59,64) 已有 signal_type / session_count
欄位，但 DB 對應 column 缺失 → decay endpoint 寫 attitude_blocks 時 raise
UndefinedColumn (psycopg.errors.UndefinedColumn: column blocks.signal_type
does not exist)，cascading 到 lint 多個 check 也 fail。

ORM 來源（models.py）:
  signal_type: VARCHAR(50) | None  (Dream Phase 2 signal extraction)
    Values: correction | preference_confirmed | repeated_pattern |
            architecture_decision | NULL
    Index: btree
  session_count: INTEGER DEFAULT 1  (Cross-session occurrence count)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p9q0r1s2t3u4"
down_revision: str | None = "n7o8p9q0r1s2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("signal_type", sa.String(50), nullable=True),
        schema="memvault",
    )
    op.create_index(
        "ix_blocks_signal_type",
        "blocks",
        ["signal_type"],
        schema="memvault",
    )
    op.add_column(
        "blocks",
        sa.Column(
            "session_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_column("blocks", "session_count", schema="memvault")
    op.drop_index("ix_blocks_signal_type", table_name="blocks", schema="memvault")
    op.drop_column("blocks", "signal_type", schema="memvault")
