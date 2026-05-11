"""triples evidence_signal + evidence_method (graphify-cannibalized)

Revision ID: q1r2s3t4u5v6
Revises: p9q0r1s2t3u4
Create Date: 2026-05-11

新增 memvault.triples 三段式證據來源欄位：
  evidence_signal: VARCHAR(16) NOT NULL DEFAULT 'extracted'
                   extracted | inferred | ambiguous
  evidence_method: VARCHAR(32) NULL
                   llm-extraction | rule-inference | fuzzy-match | manual

設計來源：graphify (MIT) 三段式信心評分
  EXTRACTED=1.0 / INFERRED=0.6-0.9 / AMBIGUOUS=0.1-0.3
重寫為 workshop style，採 server_default 安全回填既有 row。

與 blocks.signal_type (Dream Phase 2 行為類別) 語意不同：
  blocks.signal_type   = correction | preference_confirmed | repeated_pattern | architecture_decision
  triples.evidence_signal = 證據來源強度（三段式）

PG 11+ ADD COLUMN ... DEFAULT 為 metadata-only operation，不 rewrite 大表。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q1r2s3t4u5v6"
down_revision: str | None = "p9q0r1s2t3u4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "triples",
        sa.Column(
            "evidence_signal",
            sa.String(16),
            server_default=sa.text("'extracted'"),
            nullable=False,
        ),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("evidence_method", sa.String(32), nullable=True),
        schema="memvault",
    )
    # btree index on evidence_signal for filter queries
    # (e.g. WHERE evidence_signal = 'ambiguous' for verification queue)
    op.create_index(
        "ix_triples_evidence_signal",
        "triples",
        ["evidence_signal"],
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_triples_evidence_signal", table_name="triples", schema="memvault"
    )
    op.drop_column("triples", "evidence_method", schema="memvault")
    op.drop_column("triples", "evidence_signal", schema="memvault")
